"""
Catalogue, inventory and the rental price list (SPEC §4, §5.5, §6).
"""
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_
from sqlmodel import Session, select

from ..config import OPENING_HOURS, HOLIDAYS, TIME_GRID_MINUTES, MIN_RENTAL_HOURS, MAX_RENTAL_DAYS, \
    MAX_DAYS_AHEAD, MAX_OPEN_RENTALS_PER_CUSTOMER, ORDER_HOLD_DAYS, MAX_RESERVED_ORDERS_PER_CUSTOMER
from ..models.models import (
    Bike, BikeCreateRequest, BikeStatus, BikeUpdateRequest, Category, Condition, FrameSize, Order,
    OrderStatus, Purpose, Rental, RentalRate, RentalRateRequest, RentalStatus,
)
from ..timeutils import utcnow, to_local
from .errors import Conflict, NotFound, RuleViolation
from .pricing_service import money, validate_rate
from .rental_service import WEEKDAYS


class InventoryService:
    """
    Service class for bikes and prices.
    """

    # ------------------------------------------------------------ catalogue

    def search_bikes(self, db: Session, purpose: Optional[Purpose] = None, category: Optional[Category] = None,
                     frame_size: Optional[FrameSize] = None, max_price_chf: Optional[Decimal] = None,
                     condition: Optional[Condition] = None, q: Optional[str] = None) -> list[Bike]:
        """Bikes customers can see: never retired or sold ones."""
        query = select(Bike).where(Bike.status.not_in([BikeStatus.retired, BikeStatus.sold]))
        if purpose:
            query = query.where(Bike.purpose == purpose)
        if category:
            query = query.where(Bike.category == category)
        if frame_size:
            query = query.where(Bike.frame_size == frame_size)
        if condition:
            query = query.where(Bike.condition == condition)
        if max_price_chf is not None:
            query = query.where(Bike.purpose == Purpose.sale, Bike.sale_price_chf <= max_price_chf)
        if q:
            like = f"%{q.strip()}%"
            query = query.where(or_(Bike.name.ilike(like), Bike.brand.ilike(like), Bike.description.ilike(like)))
        return db.exec(query.order_by(Bike.purpose, Bike.category, Bike.code)).all()

    def get_bike(self, db: Session, bike_id: int, include_retired: bool = False) -> Bike:
        bike = db.get(Bike, bike_id)
        if not bike or (bike.status == BikeStatus.retired and not include_retired):
            raise NotFound(f"There is no bike with id {bike_id}.")
        return bike

    def all_bikes(self, db: Session) -> list[Bike]:
        """Staff view: every bike, retired included."""
        return db.exec(select(Bike).order_by(Bike.purpose, Bike.category, Bike.code)).all()

    # ------------------------------------------------------------ staff: bikes

    def create_bike(self, db: Session, request: BikeCreateRequest) -> Bike:
        if db.exec(select(Bike).where(Bike.code == request.code)).first():
            raise Conflict(f"A bike with code {request.code} already exists.")
        bike = Bike(**request.model_dump())
        db.add(bike)
        db.commit()
        db.refresh(bike)
        return bike

    def _open_rentals(self, db: Session, bike_id: int) -> list[Rental]:
        return db.exec(select(Rental).where(
            Rental.bike_id == bike_id, Rental.status.in_([RentalStatus.booked, RentalStatus.active]))).all()

    def update_bike(self, db: Session, bike_id: int, request: BikeUpdateRequest) -> Bike:
        bike = self.get_bike(db, bike_id, include_retired=True)
        if bike.status == BikeStatus.retired:
            raise Conflict(f"{bike.name} ({bike.code}) is retired and can't be changed.")
        changes = request.model_dump(exclude_unset=True)
        if "status" in changes:
            new = changes["status"]
            if bike.purpose != Purpose.rental or new not in (BikeStatus.available, BikeStatus.maintenance):
                raise RuleViolation(
                    "Only rental bikes can be switched between 'available' and 'maintenance' here. "
                    "Sale bikes change status through orders, and retiring has its own action."
                )
        if "sale_price_chf" in changes and bike.purpose != Purpose.sale:
            raise RuleViolation("A rental bike has no sale price; its price comes from the rental price list.")
        if "condition" in changes and bike.purpose == Purpose.rental and changes["condition"] == Condition.new:
            raise RuleViolation("Rental bikes are always 'used'.")
        for field, value in changes.items():
            setattr(bike, field, value)
        bike.updated_at = utcnow()
        db.add(bike)
        db.commit()
        db.refresh(bike)
        return bike

    def retire_bike(self, db: Session, bike_id: int) -> Bike:
        bike = self.get_bike(db, bike_id, include_retired=True)
        if bike.status == BikeStatus.retired:
            raise Conflict(f"{bike.name} ({bike.code}) is already retired.")
        if self._open_rentals(db, bike_id):
            raise Conflict(f"{bike.name} ({bike.code}) has booked or active rentals; cancel or finish them first.")
        if bike.status == BikeStatus.reserved:
            raise Conflict(f"{bike.name} ({bike.code}) is reserved by a customer; cancel the order first.")
        if bike.status == BikeStatus.sold:
            raise Conflict(f"{bike.name} ({bike.code}) has been sold.")
        bike.status = BikeStatus.retired
        bike.updated_at = utcnow()
        db.add(bike)
        db.commit()
        db.refresh(bike)
        return bike

    def summary(self, db: Session) -> dict:
        """Counts by purpose x category x status, plus what needs attention."""
        rows = db.exec(select(Bike.purpose, Bike.category, Bike.status, func.count(Bike.id))
                       .group_by(Bike.purpose, Bike.category, Bike.status)).all()
        now = utcnow()
        active = db.exec(select(Rental).where(Rental.status == RentalStatus.active)).all()
        booked_in_maintenance = db.exec(
            select(Rental).join(Bike, Bike.id == Rental.bike_id)
            .where(Rental.status == RentalStatus.booked, Bike.status == BikeStatus.maintenance)
        ).all()
        expiring = db.exec(select(Order).where(
            Order.status == OrderStatus.reserved, Order.expires_at <= now + timedelta(hours=24))).all()
        return {
            "counts": [{"purpose": p, "category": c, "status": s, "count": n} for p, c, s, n in rows],
            "rental_bikes_out_now": len(active),
            "overdue": [r for r in active if r.end_at < now],
            "at_risk": booked_in_maintenance,
            "expiring": expiring,
        }

    # ------------------------------------------------------------ prices & hours

    def list_rates(self, db: Session) -> list[RentalRate]:
        return db.exec(select(RentalRate).order_by(RentalRate.category)).all()

    def set_rate(self, db: Session, category: Category, request: RentalRateRequest) -> RentalRate:
        """Upsert a price. Existing bookings keep the rates stored on them."""
        validate_rate(request.hourly_chf, request.daily_chf)
        rate = db.get(RentalRate, category) or RentalRate(category=category, hourly_chf=0, daily_chf=0)
        rate.hourly_chf = money(request.hourly_chf)
        rate.daily_chf = money(request.daily_chf)
        rate.deposit_chf = money(request.deposit_chf)
        rate.updated_at = utcnow()
        db.add(rate)
        db.commit()
        db.refresh(rate)
        return rate

    def opening_hours(self) -> dict:
        today = to_local(utcnow()).date()
        weekly = []
        for i, name in enumerate(WEEKDAYS):
            hours = OPENING_HOURS.get(i)
            weekly.append({"weekday": name,
                           "opens": hours[0].strftime("%H:%M") if hours else None,
                           "closes": hours[1].strftime("%H:%M") if hours else None})
        closed = [{"date": d, "reason": r} for d, r in sorted(HOLIDAYS.items())
                  if today <= d <= today + timedelta(days=MAX_DAYS_AHEAD + MAX_RENTAL_DAYS)]
        rules = [
            "Pick-up and return must both be within opening hours (Zurich time).",
            f"Times are on the quarter hour (every {TIME_GRID_MINUTES} minutes).",
            f"A rental lasts {MIN_RENTAL_HOURS} hour to {MAX_RENTAL_DAYS} days and can be booked "
            f"up to {MAX_DAYS_AHEAD} days ahead.",
            "Price: every started hour at the hourly rate, capped at the daily rate per 24 hours.",
            "Returning early gives no refund; returning late is charged at the same rates.",
            f"A customer can have at most {MAX_OPEN_RENTALS_PER_CUSTOMER} open rentals.",
            f"A bike for sale is held for {ORDER_HOLD_DAYS} days after reserving; pay and collect it "
            f"in the shop. At most {MAX_RESERVED_ORDERS_PER_CUSTOMER} reservations per customer.",
        ]
        return {"weekly": weekly, "closed_days": closed, "rules": rules}
