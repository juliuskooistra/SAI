"""
Product analytics (SPEC §5.10): which bikes people look at, how many quotes
turn into bookings. First-party and anonymous, so no cookies or consent:
an event stores only **what** happened, **which bike** and **which day**.
No user id, no IP address, no time of day.

- `record()` is called by the routers after a successful request. It never
  raises: if the event can't be written, the error is logged and the
  customer's request still succeeds.
- `summary()` is what staff see at GET /staff/analytics.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

from pydantic import BaseModel
from sqlmodel import Session, func, select

from ..models.models import AnalyticsEvent, Bike
from ..timeutils import to_local, utcnow

logger = logging.getLogger("bikeshop.analytics")

# The events, in funnel order (SPEC §4).
EVENTS = ["catalogue_view", "bike_view", "quote", "booking", "reservation"]
TOP_BIKES = 10


# ------------------------------------------------------------ response models

class AnalyticsDay(BaseModel):
    day: date
    counts: Dict[str, int]          # event name -> count; every event listed, 0 if none


class TopBike(BaseModel):
    bike_id: int
    code: Optional[str] = None      # None if the bike was deleted since
    name: Optional[str] = None
    views: int


class AnalyticsSummary(BaseModel):
    days: int                       # length of the period
    since: date                     # first day (Zurich), included
    until: date                     # today (Zurich), included
    per_day: List[AnalyticsDay]     # one entry per day, oldest first, also days without events
    totals: Dict[str, int]          # event name -> count over the period
    top_bikes: List[TopBike]        # the 10 most-viewed bikes (bike_view), most views first
    quote_to_booking_rate: Optional[float]   # bookings / quotes, None if there were no quotes


# ------------------------------------------------------------ recording

def today() -> date:
    """Today in Zurich: analytics days are shop days."""
    return to_local(utcnow()).date()


def record(db: Session, name: str, bike_id: Optional[int] = None) -> None:
    """
    Store one anonymous event. Call it after the request's own work is done.
    Never raises (SPEC §5.10): analytics must not break a booking.
    """
    try:
        bike = db.get(Bike, bike_id) if bike_id is not None else None
        category = bike.category.value if bike else None
        db.add(AnalyticsEvent(day=today(), name=name, bike_id=bike_id, category=category))
        db.commit()
    except Exception:  # noqa: BLE001 - analytics is best effort
        logger.exception("Could not record analytics event %r", name)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------ the staff summary

def summary(db: Session, days: int = 30) -> AnalyticsSummary:
    """Counts per day and event, totals, top 10 viewed bikes, quote -> booking rate."""
    until = today()
    since = until - timedelta(days=days - 1)
    in_period = (AnalyticsEvent.day >= since) & (AnalyticsEvent.day <= until)

    # Counts per (day, event), in one query.
    rows = db.exec(
        select(AnalyticsEvent.day, AnalyticsEvent.name, func.count())
        .where(in_period)
        .group_by(AnalyticsEvent.day, AnalyticsEvent.name)
    ).all()

    # Every day of the period, with every event at 0, then fill in the counts.
    per_day = {since + timedelta(days=i): {e: 0 for e in EVENTS} for i in range(days)}
    totals = {e: 0 for e in EVENTS}
    for day, name, count in rows:
        per_day[day][name] = count
        totals[name] = totals.get(name, 0) + count

    # The most-viewed bikes.
    views = func.count().label("views")
    top = db.exec(
        select(AnalyticsEvent.bike_id, views)
        .where(in_period, AnalyticsEvent.name == "bike_view", AnalyticsEvent.bike_id.is_not(None))
        .group_by(AnalyticsEvent.bike_id)
        .order_by(views.desc(), AnalyticsEvent.bike_id)
        .limit(TOP_BIKES)
    ).all()
    top_bikes = []
    for bike_id, count in top:
        bike = db.get(Bike, bike_id)
        top_bikes.append(TopBike(bike_id=bike_id, code=bike.code if bike else None,
                                 name=bike.name if bike else None, views=count))

    quotes, bookings = totals["quote"], totals["booking"]
    return AnalyticsSummary(
        days=days, since=since, until=until,
        per_day=[AnalyticsDay(day=d, counts=c) for d, c in per_day.items()],
        totals=totals,
        top_bikes=top_bikes,
        quote_to_booking_rate=round(bookings / quotes, 3) if quotes else None,
    )
