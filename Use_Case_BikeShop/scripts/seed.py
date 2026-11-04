"""
Demo data (SPEC §9): price list, rental fleet, bikes for sale, demo accounts,
and a few rentals and orders so the staff board isn't empty.

    SEED_STAFF_PASSWORD=... SEED_CUSTOMER_PASSWORD=... [ADMIN_PASSWORD=...] python -m scripts.seed

Safe to run again: it only adds missing bikes, rates and users. Rentals and
orders are only seeded into an empty database.
"""
import os
import secrets
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlmodel import Session, select

from api.config import DEMO_ACCOUNT_TOKENS, HOLIDAYS, OPENING_HOURS, ORDER_HOLD_DAYS, SHOP_TZ
from api.database import engine, init_database
from api.models.models import (
    Bike, BikeStatus, Category, Condition, FrameSize, Order, OrderStatus, Purpose, Rental,
    RentalRate, RentalStatus, Role, User,
)
from api.services.auth_service import AuthService
from api.services.pricing_service import rental_price
from api.timeutils import to_local, utcnow

D = Decimal

# category: (hourly, daily, deposit cap) in CHF. Deposit = min(2 x price, cap) (SPEC §5.3).
RATES = {
    Category.city: (D("8"), D("35"), D("100")),
    Category.ebike: (D("15"), D("65"), D("300")),
    Category.mountain: (D("12"), D("50"), D("200")),
    Category.road: (D("12"), D("50"), D("200")),
    Category.gravel: (D("12"), D("50"), D("200")),
    Category.kids: (D("5"), D("20"), D("50")),
    Category.cargo: (D("18"), D("75"), D("400")),
}

# code, name, brand, category, size, color, year, description
RENTAL_BIKES = [
    ("R-CITY-01", "Aare Commuter 7", "Tour de Suisse", Category.city, FrameSize.M, "dark green", 2023, "7-speed hub, mudguards, rack. Easy around town."),
    ("R-CITY-02", "Aare Commuter 7", "Tour de Suisse", Category.city, FrameSize.L, "dark green", 2023, "7-speed hub, mudguards, rack. Easy around town."),
    ("R-CITY-03", "Marzili Step-Through", "Tour de Suisse", Category.city, FrameSize.S, "cream", 2022, "Low step-through frame, basket at the front."),
    ("R-CITY-04", "Marzili Step-Through", "Tour de Suisse", Category.city, FrameSize.M, "cream", 2022, "Low step-through frame, basket at the front."),
    ("R-EBIKE-01", "Upstreet 5", "Flyer", Category.ebike, FrameSize.M, "anthracite", 2024, "Bosch motor, 625 Wh battery, about 100 km range."),
    ("R-EBIKE-02", "Upstreet 5", "Flyer", Category.ebike, FrameSize.L, "anthracite", 2024, "Bosch motor, 625 Wh battery, about 100 km range."),
    ("R-EBIKE-03", "Gotour 6", "Flyer", Category.ebike, FrameSize.S, "white", 2024, "Comfortable tour e-bike with low step-in."),
    ("R-EBIKE-04", "Gotour 6", "Flyer", Category.ebike, FrameSize.M, "white", 2023, "Comfortable tour e-bike with low step-in."),
    ("R-EBIKE-05", "Stromer ST3", "Stromer", Category.ebike, FrameSize.L, "black", 2023, "Fast S-pedelec feel, up to 45 km/h with licence plate."),
    ("R-MTB-01", "Spectral 7", "Canyon", Category.mountain, FrameSize.M, "olive", 2023, "Full suspension trail bike, 150 mm travel."),
    ("R-MTB-02", "Spectral 7", "Canyon", Category.mountain, FrameSize.L, "olive", 2023, "Full suspension trail bike, 150 mm travel."),
    ("R-MTB-03", "Talon 2", "Giant", Category.mountain, FrameSize.S, "red", 2022, "Hardtail for forest roads and easy trails."),
    ("R-ROAD-01", "Endurace 7", "Canyon", Category.road, FrameSize.M, "blue", 2024, "Endurance road bike, Shimano 105."),
    ("R-ROAD-02", "Endurace 7", "Canyon", Category.road, FrameSize.L, "blue", 2024, "Endurance road bike, Shimano 105."),
    ("R-GRAV-01", "Topstone 2", "Cannondale", Category.gravel, FrameSize.M, "sage", 2023, "Gravel bike with 40 mm tyres, for Emmental back roads."),
    ("R-GRAV-02", "Topstone 2", "Cannondale", Category.gravel, FrameSize.L, "sage", 2023, "Gravel bike with 40 mm tyres, for Emmental back roads."),
    ("R-KIDS-01", "Kids 20", "Woom", Category.kids, FrameSize.XS, "yellow", 2023, "For kids about 6 to 8 years old."),
    ("R-KIDS-02", "Kids 24", "Woom", Category.kids, FrameSize.XS, "red", 2023, "For kids about 8 to 11 years old."),
    ("R-CARGO-01", "Load 75", "Riese & Müller", Category.cargo, FrameSize.M, "grey", 2023, "Electric cargo bike, carries two kids or 100 kg."),
    ("R-CARGO-02", "Packster 70", "Riese & Müller", Category.cargo, FrameSize.M, "grey", 2022, "Electric cargo bike with rain cover."),
]
MAINTENANCE = "R-MTB-03"

# code, name, brand, category, size, color, year, condition, price, description
SALE_BIKES = [
    ("S-CITY-01", "Aare Commuter 7", "Tour de Suisse", Category.city, FrameSize.M, "dark green", 2025, Condition.new, D("890"), "7-speed hub, mudguards, rack."),
    ("S-CITY-02", "Marzili Step-Through", "Tour de Suisse", Category.city, FrameSize.S, "cream", 2022, Condition.used, D("420"), "Ex-rental, serviced, new tyres."),
    ("S-CITY-03", "Crossway 40", "Merida", Category.city, FrameSize.L, "black", 2025, Condition.new, D("1090"), "Hybrid with front suspension."),
    ("S-EBIKE-01", "Upstreet 5", "Flyer", Category.ebike, FrameSize.M, "anthracite", 2025, Condition.new, D("4290"), "Bosch motor, 625 Wh battery."),
    ("S-EBIKE-02", "Gotour 6", "Flyer", Category.ebike, FrameSize.M, "white", 2022, Condition.used, D("2190"), "Ex-rental, battery tested at 92%."),
    ("S-EBIKE-03", "Stromer ST5", "Stromer", Category.ebike, FrameSize.L, "black", 2025, Condition.new, D("5990"), "S-pedelec, 45 km/h, 983 Wh battery."),
    ("S-MTB-01", "Spectral 7", "Canyon", Category.mountain, FrameSize.M, "olive", 2025, Condition.new, D("3499"), "Full suspension trail bike."),
    ("S-MTB-02", "Talon 2", "Giant", Category.mountain, FrameSize.M, "red", 2021, Condition.used, D("490"), "Hardtail, serviced."),
    ("S-ROAD-01", "Endurace 7", "Canyon", Category.road, FrameSize.L, "blue", 2025, Condition.new, D("1899"), "Endurance road bike, Shimano 105."),
    ("S-ROAD-02", "Allez", "Specialized", Category.road, FrameSize.S, "white", 2020, Condition.used, D("650"), "Aluminium road bike, Claris groupset."),
    ("S-GRAV-01", "Topstone 3", "Cannondale", Category.gravel, FrameSize.M, "sage", 2025, Condition.new, D("1490"), "Gravel bike, 2x10 gears."),
    ("S-GRAV-02", "Grizl 6", "Canyon", Category.gravel, FrameSize.L, "black", 2024, Condition.new, D("1749"), "Gravel bike with rack mounts."),
    ("S-KIDS-01", "Kids 16", "Woom", Category.kids, FrameSize.XS, "blue", 2025, Condition.new, D("549"), "For kids about 4 to 6 years old."),
    ("S-KIDS-02", "Kids 24", "Woom", Category.kids, FrameSize.XS, "green", 2021, Condition.used, D("400"), "Outgrown, good condition."),
    ("S-CARGO-01", "Load 60", "Riese & Müller", Category.cargo, FrameSize.M, "grey", 2025, Condition.new, D("5800"), "Electric cargo bike, child seat included."),
]


def at(day: date, hh: int, mm: int = 0) -> datetime:
    """A Zurich wall-clock time on `day`, as UTC (seeded times follow the shop's rules)."""
    return datetime.combine(day, time(hh, mm), tzinfo=SHOP_TZ).astimezone(timezone.utc)


def closing(day: date, minutes_before: int = 0) -> datetime:
    """`minutes_before` the shop closes on `day` (Saturdays close at 16:00)."""
    closes = OPENING_HOURS.get(day.weekday(), (time(9), time(18, 30)))[1]
    return datetime.combine(day, closes, tzinfo=SHOP_TZ).astimezone(timezone.utc) - timedelta(minutes=minutes_before)


def open_day(day: date, step: int = 1) -> date:
    """`day`, or the nearest open day after (step=1) or before (step=-1) it."""
    while day.weekday() not in OPENING_HOURS or day in HOLIDAYS:
        day += timedelta(days=step)
    return day


def ensure_user(db: Session, username: str, email: str, password: str, role: Role, tokens: float) -> User:
    user = db.exec(select(User).where(User.username == username)).first()
    if user:
        return user
    user = AuthService().register_user(username, email, password, db, role=role)
    user.token_balance = user.total_tokens_purchased = tokens
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"  user {username} ({role.value})")
    return user


def seed_catalogue(db: Session) -> dict[str, Bike]:
    for category, (hourly, daily, deposit) in RATES.items():
        if not db.get(RentalRate, category):
            db.add(RentalRate(category=category, hourly_chf=hourly, daily_chf=daily, deposit_chf=deposit))
    for code, name, brand, cat, size, color, year, desc in RENTAL_BIKES:
        if not db.exec(select(Bike).where(Bike.code == code)).first():
            db.add(Bike(code=code, name=name, brand=brand, category=cat, frame_size=size, color=color, year=year,
                        purpose=Purpose.rental, condition=Condition.used, description=desc,
                        status=BikeStatus.maintenance if code == MAINTENANCE else BikeStatus.available))
    for code, name, brand, cat, size, color, year, cond, price, desc in SALE_BIKES:
        if not db.exec(select(Bike).where(Bike.code == code)).first():
            db.add(Bike(code=code, name=name, brand=brand, category=cat, frame_size=size, color=color, year=year,
                        purpose=Purpose.sale, condition=cond, sale_price_chf=price, description=desc))
    db.commit()
    return {b.code: b for b in db.exec(select(Bike)).all()}


def seed_activity(db: Session, bikes: dict[str, Bike], customer: User, lena: User, marco: User) -> None:
    """Rentals and orders relative to now, for the staff board. Only into an empty database."""
    if db.exec(select(Rental)).first() or db.exec(select(Order)).first():
        print("  rentals/orders exist, skipped")
        return
    now = utcnow()
    today = to_local(now).date()
    past = open_day(today - timedelta(days=6), -1)
    yesterday = open_day(today - timedelta(days=1), -1)
    before = open_day(yesterday - timedelta(days=1), -1)
    soon = open_day(today + timedelta(days=2))
    later = open_day(soon + timedelta(days=1))

    def rental(code, user, start, end, status, picked=None, returned=None):
        bike = bikes[code]
        rate = db.get(RentalRate, bike.category)
        quoted = rental_price(start, end, rate.hourly_chf, rate.daily_chf).total_chf
        final = rental_price(start, max(end, returned), rate.hourly_chf, rate.daily_chf).total_chf if returned else None
        db.add(Rental(bike_id=bike.id, user_id=user.user_id, start_at=start, end_at=end, status=status,
                      hourly_chf=rate.hourly_chf, daily_chf=rate.daily_chf, quoted_price_chf=quoted,
                      picked_up_at=picked, returned_at=returned, final_price_chf=final,
                      created_at=min(start - timedelta(days=2), now - timedelta(hours=1))))

    # Past and returned
    rental("R-CITY-01", customer, at(past, 10), at(past, 14), RentalStatus.returned,
           picked=at(past, 10), returned=at(past, 14))
    rental("R-ROAD-01", lena, at(past, 9), closing(past, 60), RentalStatus.returned,
           picked=at(past, 9, 15), returned=closing(past, 15))
    # Overdue: should have come back yesterday
    rental("R-EBIKE-05", marco, at(before, 10), closing(yesterday, 60), RentalStatus.active, picked=at(before, 10, 15))
    # Out now, due back later today
    rental("R-EBIKE-01", lena, at(yesterday, 10), closing(today, 30), RentalStatus.active, picked=at(yesterday, 10))
    # To pick up later today
    rental("R-CARGO-01", marco, closing(today, 90), closing(today), RentalStatus.booked)
    # The demo customer's own future booking
    rental("R-GRAV-01", customer, at(later, 10), at(later, 16), RentalStatus.booked)
    # At risk: booked, but the bike is in maintenance
    rental(MAINTENANCE, lena, at(soon, 10), at(soon, 14), RentalStatus.booked)

    # Reserved sale bike that expires within a day, and a completed sale
    bike = bikes["S-EBIKE-02"]
    # Expires at the next 12:00 (within 24 hours), not in the middle of the night
    expires = at(today, 12) if at(today, 12) > now else at(today + timedelta(days=1), 12)
    db.add(Order(bike_id=bike.id, user_id=marco.user_id, price_chf=bike.sale_price_chf, status=OrderStatus.reserved,
                 created_at=expires - timedelta(days=ORDER_HOLD_DAYS), expires_at=expires))
    bike.status = BikeStatus.reserved
    sold = bikes["S-MTB-02"]
    db.add(Order(bike_id=sold.id, user_id=lena.user_id, price_chf=sold.sale_price_chf, status=OrderStatus.completed,
                 created_at=at(past, 11) - timedelta(days=4), expires_at=at(past, 11) + timedelta(days=3), closed_at=at(past, 11)))
    sold.status = BikeStatus.sold
    db.add(bike)
    db.add(sold)
    db.commit()
    print("  rentals and orders")


def main() -> None:
    staff_pw = os.getenv("SEED_STAFF_PASSWORD")
    customer_pw = os.getenv("SEED_CUSTOMER_PASSWORD")
    if not staff_pw or not customer_pw or min(len(staff_pw), len(customer_pw)) < 10:
        raise SystemExit("Set SEED_STAFF_PASSWORD and SEED_CUSTOMER_PASSWORD (at least 10 characters each).")
    admin_pw = os.getenv("ADMIN_PASSWORD")
    if admin_pw and len(admin_pw) < 10:
        raise SystemExit("ADMIN_PASSWORD needs at least 10 characters.")

    init_database()
    with Session(engine) as db:
        print("Seeding:")
        ensure_user(db, "staff", "staff@bikeshop.test", staff_pw, Role.staff, DEMO_ACCOUNT_TOKENS)
        if admin_pw:
            ensure_user(db, "admin", "admin@bikeshop.test", admin_pw, Role.staff, DEMO_ACCOUNT_TOKENS)
        else:
            print("  no admin account (set ADMIN_PASSWORD to create one)")
        customer = ensure_user(db, "customer", "customer@bikeshop.test", customer_pw, Role.customer, DEMO_ACCOUNT_TOKENS)
        lena = ensure_user(db, "lena", "lena@bikeshop.test", secrets.token_urlsafe(24), Role.customer, DEMO_ACCOUNT_TOKENS)
        marco = ensure_user(db, "marco", "marco@bikeshop.test", secrets.token_urlsafe(24), Role.customer, DEMO_ACCOUNT_TOKENS)
        bikes = seed_catalogue(db)
        print(f"  {len(bikes)} bikes, {len(RATES)} rental rates")
        seed_activity(db, bikes, customer, lena, marco)
    print("Done.")


if __name__ == "__main__":
    main()
