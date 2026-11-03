"""
Rentals: rules, quotes, availability, bookings, pick-up and return (SPEC §5.1-5.5).

Every method takes a Session and plain arguments and never reads a Request,
so the LLM tools can call it directly (SPEC §8.3). Times in and out are
aware UTC; routers convert at the edge.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, and_, update
from sqlmodel import Session, select

from ..config import (
    OPENING_HOURS, HOLIDAYS, SHOP_TZ, TIME_GRID_MINUTES, MIN_RENTAL_HOURS,
    MAX_RENTAL_DAYS, MAX_DAYS_AHEAD, MAX_OPEN_RENTALS_PER_CUSTOMER,
)
from ..database import start_write_transaction
from ..models.models import (
    Bike, BikeStatus, Category, FrameSize, Purpose, Rental, RentalRate, RentalStatus, User,
)
from ..timeutils import utcnow, to_local, format_local
from .errors import Conflict, NotFound, RuleViolation
from .pricing_service import PriceBreakdown, rental_price

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
OPEN_STATUSES = (RentalStatus.booked, RentalStatus.active)


class RentalService:
    """
    Service class for rentals.
    """

    # ------------------------------------------------------------ rules

    def _check_open(self, moment: datetime, what: str) -> None:
        """moment (UTC) must fall within opening hours in Zurich."""
        local = to_local(moment)
        if local.date() in HOLIDAYS:
            raise RuleViolation(
                f"The shop is closed on {local.day} {local:%b} ({HOLIDAYS[local.date()]}). "
                f"Choose another {what} day."
            )
        hours = OPENING_HOURS.get(local.weekday())
        if hours is None:
            raise RuleViolation(
                f"The shop is closed on {WEEKDAYS[local.weekday()]}s. Choose a {what} time "
                f"between Monday and Saturday."
            )
        opens, closes = hours
        if not (opens <= local.time() <= closes):
            raise RuleViolation(
                f"The {what} time must be within opening hours: {WEEKDAYS[local.weekday()]} "
                f"{opens:%H:%M}-{closes:%H:%M}."
            )

    def validate_period(self, start: datetime, end: datetime, now: Optional[datetime] = None) -> None:
        """Check a rental period against SPEC §5.1-5.2. Raises RuleViolation."""
        now = now or utcnow()
        for moment, what in ((start, "pick-up"), (end, "return")):
            local = to_local(moment)
            if local.minute % TIME_GRID_MINUTES or local.second or local.microsecond:
                raise RuleViolation(
                    f"The {what} time must be on the quarter hour (:00, :15, :30 or :45), "
                    f"not {local:%H:%M}."
                )
        if start <= now:
            raise RuleViolation("The pick-up time must be in the future.")
        if start > now + timedelta(days=MAX_DAYS_AHEAD):
            raise RuleViolation(f"Bookings can be made at most {MAX_DAYS_AHEAD} days ahead.")
        if end <= start:
            raise RuleViolation("The return time must be after the pick-up time.")
        if end - start < timedelta(hours=MIN_RENTAL_HOURS):
            raise RuleViolation(f"A rental lasts at least {MIN_RENTAL_HOURS} hour.")
        if end - start > timedelta(days=MAX_RENTAL_DAYS):
            raise RuleViolation(f"A rental lasts at most {MAX_RENTAL_DAYS} days.")
        self._check_open(start, "pick-up")
        self._check_open(end, "return")

    # ------------------------------------------------------------ lookups

    def _rental_bike(self, db: Session, bike_id: int) -> Bike:
        bike = db.get(Bike, bike_id)
        if not bike or bike.status == BikeStatus.retired:
            raise NotFound(f"There is no bike with id {bike_id}.")
        if bike.purpose != Purpose.rental:
            raise Conflict(f"{bike.name} ({bike.code}) is for sale, not for rent.")
        return bike

    def _rate(self, db: Session, category: Category) -> RentalRate:
        rate = db.get(RentalRate, category)
        if not rate:
            raise Conflict(f"There is no rental price for {category.value} bikes yet.")
        return rate

    def _blocking_rental(self, db: Session, bike_id: int, start: datetime, end: datetime,
                         now: datetime) -> Optional[Rental]:
        """A booked/active rental that overlaps [start, end), or an overdue one (SPEC §5.4)."""
        return db.exec(
            select(Rental).where(
                Rental.bike_id == bike_id,
                Rental.status.in_(OPEN_STATUSES),
                or_(
                    and_(Rental.start_at < end, Rental.end_at > start),
                    and_(Rental.status == RentalStatus.active, Rental.end_at < now),
                ),
            )
        ).first()

    def _taken_message(self, bike: Bike, other: Rental, now: datetime) -> str:
        if other.status == RentalStatus.active and other.end_at < now:
            return f"{bike.name} ({bike.code}) hasn't been returned from its last rental yet."
        return (f"{bike.name} ({bike.code}) is already booked from {format_local(other.start_at)} "
                f"to {format_local(other.end_at)}.")

    # ------------------------------------------------------------ quotes & availability

    def quote(self, db: Session, bike_id: int, start: datetime, end: datetime) -> tuple[Bike, RentalRate, PriceBreakdown]:
        """Price for renting one bike; books nothing and doesn't check availability."""
        self.validate_period(start, end)
        bike = self._rental_bike(db, bike_id)
        rate = self._rate(db, bike.category)
        return bike, rate, rental_price(start, end, rate.hourly_chf, rate.daily_chf)

    def available_bikes(self, db: Session, start: datetime, end: datetime,
                        category: Optional[Category] = None,
                        frame_size: Optional[FrameSize] = None) -> list[tuple[Bike, RentalRate, PriceBreakdown]]:
        """Rental bikes free for [start, end), each with its price."""
        self.validate_period(start, end)
        now = utcnow()
        query = select(Bike).where(Bike.purpose == Purpose.rental, Bike.status == BikeStatus.available)
        if category:
            query = query.where(Bike.category == category)
        if frame_size:
            query = query.where(Bike.frame_size == frame_size)
        result = []
        for bike in db.exec(query.order_by(Bike.category, Bike.code)).all():
            if self._blocking_rental(db, bike.id, start, end, now):
                continue
            rate = db.get(RentalRate, bike.category)
            if rate:
                result.append((bike, rate, rental_price(start, end, rate.hourly_chf, rate.daily_chf)))
        return result

    # ------------------------------------------------------------ booking

    def book(self, db: Session, user_id: str, bike_id: int, start: datetime, end: datetime) -> Rental:
        """
        Book a bike. Check and insert happen in one BEGIN IMMEDIATE transaction,
        so two customers can't book the same bike for overlapping times.
        """
        self.validate_period(start, end)
        start_write_transaction(db)
        try:
            now = utcnow()
            bike = self._rental_bike(db, bike_id)
            if bike.status != BikeStatus.available:
                raise Conflict(f"{bike.name} ({bike.code}) is in maintenance and can't be booked right now.")
            other = self._blocking_rental(db, bike.id, start, end, now)
            if other:
                raise Conflict(self._taken_message(bike, other, now))
            open_count = len(db.exec(select(Rental.id).where(
                Rental.user_id == user_id, Rental.status.in_(OPEN_STATUSES))).all())
            if open_count >= MAX_OPEN_RENTALS_PER_CUSTOMER:
                raise Conflict(
                    f"You already have {open_count} open rentals; the limit is "
                    f"{MAX_OPEN_RENTALS_PER_CUSTOMER}. Cancel or return one first."
                )
            rate = self._rate(db, bike.category)
            price = rental_price(start, end, rate.hourly_chf, rate.daily_chf)
            rental = Rental(
                bike_id=bike.id, user_id=user_id, start_at=start, end_at=end,
                status=RentalStatus.booked, hourly_chf=rate.hourly_chf, daily_chf=rate.daily_chf,
                quoted_price_chf=price.total_chf,
            )
            db.add(rental)
            db.commit()
            db.refresh(rental)
            return rental
        except Exception:
            db.rollback()
            raise

    # ------------------------------------------------------------ reading

    def list_rentals(self, db: Session, user_id: Optional[str] = None, status: Optional[RentalStatus] = None,
                     on_date=None, bike_id: Optional[int] = None, overdue: Optional[bool] = None) -> list[Rental]:
        """Rentals, newest start first. on_date = a Zurich date the rental starts or ends on."""
        query = select(Rental)
        if user_id:
            query = query.where(Rental.user_id == user_id)
        if status:
            query = query.where(Rental.status == status)
        if bike_id:
            query = query.where(Rental.bike_id == bike_id)
        if overdue:
            query = query.where(Rental.status == RentalStatus.active, Rental.end_at < utcnow())
        rentals = db.exec(query.order_by(Rental.start_at.desc())).all()
        if on_date:
            rentals = [r for r in rentals
                       if to_local(r.start_at).date() == on_date or to_local(r.end_at).date() == on_date]
        return rentals

    def get_rental(self, db: Session, rental_id: int, user_id: Optional[str] = None) -> Rental:
        """One rental; with user_id, only if it belongs to that user (else 404)."""
        rental = db.get(Rental, rental_id)
        if not rental or (user_id and rental.user_id != user_id):
            raise NotFound(f"There is no rental with id {rental_id} on your account.")
        return rental

    # ------------------------------------------------------------ lifecycle

    def _transition(self, db: Session, rental_id: int, from_status: RentalStatus, **values) -> bool:
        """Change status only if it is still from_status. True if this call changed it."""
        result = db.execute(
            update(Rental).where(Rental.id == rental_id, Rental.status == from_status).values(**values)
        )
        return result.rowcount == 1

    def cancel(self, db: Session, rental_id: int, user_id: Optional[str] = None) -> Rental:
        """
        Cancel a booked rental. With user_id (customer), only their own and only
        before it starts; without (staff), any booked rental.
        """
        start_write_transaction(db)
        try:
            rental = self.get_rental(db, rental_id, user_id)
            if rental.status != RentalStatus.booked:
                raise Conflict(f"This rental is {rental.status.value}; only booked rentals can be cancelled.")
            if user_id and utcnow() >= rental.start_at:
                raise Conflict("This rental has already started; ask the shop staff to cancel it.")
            self._transition(db, rental_id, RentalStatus.booked, status=RentalStatus.cancelled)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(rental)
        return rental

    def pickup(self, db: Session, rental_id: int) -> Rental:
        """Staff hands the bike over: booked -> active, only on the start date."""
        start_write_transaction(db)
        try:
            rental = self.get_rental(db, rental_id)
            if rental.status != RentalStatus.booked:
                raise Conflict(f"This rental is {rental.status.value}; only booked rentals can be picked up.")
            now = utcnow()
            if to_local(rental.start_at).date() != to_local(now).date():
                raise Conflict(f"This rental starts on {format_local(rental.start_at)}; "
                               f"it can only be picked up on that day.")
            self._transition(db, rental_id, RentalStatus.booked, status=RentalStatus.active, picked_up_at=now)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(rental)
        return rental

    def return_bike(self, db: Session, rental_id: int) -> Rental:
        """
        Staff takes the bike back: active -> returned. Final price at the rates
        stored on the rental, for start..max(planned end, now): no refund when
        early, same rates when late (SPEC §5.3).
        """
        start_write_transaction(db)
        try:
            rental = self.get_rental(db, rental_id)
            if rental.status != RentalStatus.active:
                raise Conflict(f"This rental is {rental.status.value}; only active rentals can be returned.")
            now = utcnow()
            final = rental_price(rental.start_at, max(rental.end_at, now), rental.hourly_chf, rental.daily_chf)
            self._transition(db, rental_id, RentalStatus.active, status=RentalStatus.returned,
                             returned_at=now, final_price_chf=final.total_chf)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(rental)
        return rental

    # ------------------------------------------------------------ for responses

    def describe(self, db: Session, rental: Rental, with_username: bool = False) -> dict:
        """Rental plus bike name/code and computed flags, ready for RentalResponse."""
        bike = db.get(Bike, rental.bike_id)
        data = rental.model_dump()
        data.update(
            bike_code=bike.code, bike_name=bike.name,
            overdue=rental.status == RentalStatus.active and rental.end_at < utcnow(),
            at_risk=rental.status == RentalStatus.booked and bike.status == BikeStatus.maintenance,
        )
        if with_username:
            user = db.exec(select(User).where(User.user_id == rental.user_id)).first()
            data["username"] = user.username if user else None
        return data
