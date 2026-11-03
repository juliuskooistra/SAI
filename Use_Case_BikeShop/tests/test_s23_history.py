"""S23 a year of past usage (SPEC §9.1, §11)."""
from collections import Counter
from datetime import timedelta
from statistics import median

import pytest
from sqlmodel import Session, func, select

from api.config import HOLIDAYS, OPENING_HOURS
from api.database import engine
from api.models.models import AnalyticsEvent, Bike, Category, Order, OrderStatus, Rental, RentalStatus, User
from api.services.pricing_service import rental_price
from api.timeutils import to_local, utcnow
from scripts import seed, seed_history
from scripts.seed_history import june_first, school_holiday

from .conftest import NOW


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    seed_history.main()
    with Session(engine) as db:
        guests = {u.user_id for u in db.exec(select(User).where(User.username.like("guest%"))).all()}
        bikes = {b.id: b for b in db.exec(select(Bike)).all()}
        rentals = [r for r in db.exec(select(Rental)).all() if r.user_id in guests]
        orders = [o for o in db.exec(select(Order)).all() if o.user_id in guests]
        events = db.exec(select(AnalyticsEvent)).all()
    return bikes, rentals, orders, events


def _counts():
    with Session(engine) as db:
        return tuple(db.exec(select(func.count()).select_from(t)).one()
                     for t in (User, Bike, Rental, Order, AnalyticsEvent))


def local_day(dt):
    return to_local(dt).date()


def test_runs_once_and_demo_customer_can_still_book(history, client):
    first = _counts()
    seed_history.main()
    assert _counts() == first
    r = client.post("/auth/generate-key", json={"username": "customer", "password": "customer-pass-123", "name": "t"})
    headers = {"Authorization": f"Bearer {r.json()['api_key']}"}
    bikes = client.get("/api/availability", params={"start_at": "2026-11-07T10:00", "end_at": "2026-11-07T15:00",
                                                    "category": "ebike"}, headers=headers).json()["bikes"]
    r = client.post("/api/rentals", json={"bike_id": bikes[0]["bike"]["id"], "start_at": "2026-11-07T10:00",
                                          "end_at": "2026-11-07T15:00"}, headers=headers)
    assert r.status_code == 200


def test_rentals_follow_the_rules(history):
    _, rentals, _, _ = history
    assert len(rentals) > 500
    with Session(engine) as db:
        everything = db.exec(select(Rental).where(Rental.status != RentalStatus.cancelled)).all()
    for r in rentals:
        for t in (r.start_at, r.end_at):
            local = to_local(t)
            assert local.weekday() in OPENING_HOURS and local.date() not in HOLIDAYS
            opens, closes = OPENING_HOURS[local.weekday()]
            assert opens <= local.time() <= closes and local.minute % 15 == 0
        assert timedelta(hours=1) <= r.end_at - r.start_at <= timedelta(days=14)
        assert r.end_at < NOW and r.created_at < r.start_at
        assert r.status in (RentalStatus.returned, RentalStatus.cancelled)
        assert r.quoted_price_chf == rental_price(r.start_at, r.end_at, r.hourly_chf, r.daily_chf).total_chf
        if r.status == RentalStatus.returned:
            assert r.returned_at < NOW
            back = max(r.end_at, r.returned_at)
            assert r.final_price_chf == rental_price(r.start_at, back, r.hourly_chf, r.daily_chf).total_chf
    by_bike = {}
    for r in everything:
        by_bike.setdefault(r.bike_id, []).append(r)
    for same_bike in by_bike.values():
        same_bike.sort(key=lambda r: r.start_at)
        for a, b in zip(same_bike, same_bike[1:]):
            assert a.end_at <= b.start_at, f"rentals {a.id} and {b.id} overlap"


def test_events_agree_with_rentals_and_orders(history):
    _, rentals, orders, events = history
    bookings = Counter(e.day for e in events if e.name == "booking")
    reservations = Counter(e.day for e in events if e.name == "reservation")
    assert bookings == Counter(local_day(r.created_at) for r in rentals)
    assert reservations == Counter(local_day(o.created_at) for o in orders)
    today = to_local(NOW).date()
    assert min(e.day for e in events) >= today - timedelta(days=365)
    assert max(e.day for e in events) < today


def test_planted_patterns(history):
    bikes, rentals, orders, events = history
    returned = [r for r in rentals if r.status == RentalStatus.returned]
    start_month = Counter(local_day(r.start_at).month for r in returned)
    assert start_month[7] > 2 * start_month[1]                                               # P1

    large = {b.id for b in bikes.values() if b.code in ("R-EBIKE-02", "R-EBIKE-05")}
    today = to_local(NOW).date()
    saturdays = [today - timedelta(days=n) for n in range(1, 366)]
    saturdays = [d for d in saturdays if d.weekday() == 5 and 5 <= d.month <= 9 and d not in HOLIDAYS]
    for bike_id in large:                                                                    # P2
        out = sum(any(local_day(r.start_at) <= d <= local_day(r.end_at) for r in returned if r.bike_id == bike_id)
                  for d in saturdays)
        assert out >= .8 * len(saturdays)

    fleet = Counter(b.category for b in bikes.values() if b.code.startswith("R-"))
    per_bike = {cat: sum(1 for r in returned if bikes[r.bike_id].category == cat) / fleet[cat]
                for cat in fleet if cat != Category.kids}
    assert min(per_bike, key=per_bike.get) == Category.cargo                                 # P3

    kids = [r for r in returned if bikes[r.bike_id].category == Category.kids]
    assert sum(school_holiday(local_day(r.start_at)) for r in kids) >= .8 * len(kids)       # P4

    june = june_first(today)
    ebike = [r for r in rentals if bikes[r.bike_id].category == Category.ebike]
    assert all((r.hourly_chf, r.daily_chf) == ((14, 60) if local_day(r.created_at) < june else (15, 65))
               for r in ebike)                                                               # P5
    booked_month = Counter(local_day(r.created_at).month for r in ebike)
    assert booked_month[6] >= booked_month[5]

    def gravel_share(months):
        chosen = [r for r in returned if local_day(r.start_at).month in months]
        return sum(bikes[r.bike_id].category == Category.gravel for r in chosen) / len(chosen)
    assert gravel_share({8, 9, 10}) >= 1.5 * gravel_share({11, 12, 1})                       # P6

    by_code = {b.code: b for b in bikes.values()}
    with Session(engine) as db:
        all_orders = db.exec(select(Order)).all()
    stromer, road = by_code["S-EBIKE-03"], by_code["S-ROAD-02"]                              # P7
    assert (today - local_day(stromer.created_at)).days == 100
    assert not [o for o in all_orders if o.bike_id == stromer.id]
    assert (today - local_day(road.created_at)).days == 140
    assert [o.status for o in all_orders if o.bike_id == road.id] == [OrderStatus.expired] * 2

    views = Counter(e.day for e in events if e.name == "catalogue_view")
    spikes = [d for d, n in views.items() if n >= 4 * median(views.values())]               # P8
    assert len(spikes) == 1 and spikes[0].month == 4


def test_staff_sees_the_year(history, client, monkeypatch):
    r = client.post("/auth/generate-key", json={"username": "staff", "password": "staff-pass-123", "name": "t"})
    staff = {"Authorization": f"Bearer {r.json()['api_key']}"}
    body = client.get("/staff/analytics", params={"days": 365}, headers=staff).json()
    assert len(body["per_day"]) == 365 and body["totals"]["booking"] > 500
