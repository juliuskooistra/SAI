"""
A year of invented past usage (SPEC §9.1): customers, rentals, sales and
analytics events for the 365 days up to yesterday, so staff analytics and
the management agents have something to work with.

    python -m scripts.seed_history        # after python -m scripts.seed

The data is random, but with planted patterns (P1–P8 in SPEC §9.1): the
answer key that an analysis should find. Every rental follows the shop's
rules (opening hours, 15-minute grid, no double booking, prices) and ends
before today, so nothing on today's board changes.

Runs once: if `guest001` exists, it does nothing.
"""
import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from api.config import HOLIDAYS, OPENING_HOURS, ORDER_HOLD_DAYS
from api.database import engine, init_database
from api.models.models import (
    AnalyticsEvent, Bike, BikeStatus, Category, Condition, FrameSize, Order, OrderStatus, Purpose,
    Rental, RentalStatus, User,
)
from api.services.auth_service import AuthService
from api.services.pricing_service import rental_price
from api.timeutils import to_local, utcnow
from scripts.seed import RATES, RENTAL_BIKES, SALE_BIKES, at

D = Decimal
RANDOM_SEED = 2026
GUESTS = 120
DAYS = 365

# ---------------------------------------------------------------- demand model

# How busy each month is, relative to May (P1)
SEASON = {1: .25, 2: .3, 3: .5, 4: .8, 5: 1.0, 6: 1.2, 7: 1.25, 8: 1.2, 9: .95, 10: .6, 11: .35, 12: .25}

# Chance that a free bike gets a rental starting on an open weekday in May (P1, P3, P6)
BASE_CHANCE = {
    Category.city: .22, Category.ebike: .22, Category.mountain: .18, Category.road: .18,
    Category.gravel: .10, Category.cargo: .035,
}

# Invented school holidays, roughly Bern's: (first month, day), (last month, day) (P4)
SCHOOL_HOLIDAYS = [((1, 1), (1, 4)), ((4, 4), (4, 19)), ((7, 4), (8, 9)), ((9, 26), (10, 18)), ((12, 20), (12, 31))]

# Share of rentals that last a few hours, one day; the rest last several days (P3)
DURATION_MIX = {Category.ebike: (.4, .4), Category.cargo: (.15, .3), Category.kids: (.3, .4)}
DEFAULT_MIX = (.55, .35)
MAX_DAYS = {Category.cargo: 7, Category.ebike: 6, Category.kids: 6}

# E-bike prices before 1 June (P5); from then on the current price list applies
EBIKE_RATES_BEFORE_JUNE = (D("14"), D("60"))

# Sale bikes sold during the year (P7):
# name, brand, category, size, color, year, condition, price, (min, max) days until reserved, how many
SOLD_BIKES = [
    ("Upstreet 5", "Flyer", Category.ebike, FrameSize.M, "anthracite", 2025, Condition.new, D("4290"), (3, 14), 3),
    ("Gotour 6", "Flyer", Category.ebike, FrameSize.S, "white", 2025, Condition.new, D("3890"), (3, 14), 2),
    ("Gotour 6", "Flyer", Category.ebike, FrameSize.M, "white", 2022, Condition.used, D("2190"), (5, 14), 1),
    ("Stromer ST3", "Stromer", Category.ebike, FrameSize.L, "black", 2022, Condition.used, D("3200"), (20, 45), 1),
    ("Marzili Step-Through", "Tour de Suisse", Category.city, FrameSize.M, "cream", 2021, Condition.used, D("380"), (2, 12), 2),
    ("Aare Commuter 7", "Tour de Suisse", Category.city, FrameSize.M, "dark green", 2025, Condition.new, D("890"), (7, 30), 2),
    ("Crossway 40", "Merida", Category.city, FrameSize.L, "black", 2025, Condition.new, D("1090"), (7, 30), 1),
    ("Talon 2", "Giant", Category.mountain, FrameSize.S, "red", 2020, Condition.used, D("450"), (2, 12), 1),
    ("Spectral 7", "Canyon", Category.mountain, FrameSize.L, "olive", 2025, Condition.new, D("3499"), (14, 45), 2),
    ("Endurace 7", "Canyon", Category.road, FrameSize.M, "blue", 2025, Condition.new, D("1899"), (14, 45), 2),
    ("Allez", "Specialized", Category.road, FrameSize.M, "red", 2019, Condition.used, D("600"), (60, 120), 1),
    ("Domane AL 2", "Trek", Category.road, FrameSize.L, "grey", 2020, Condition.used, D("690"), (60, 120), 1),
    ("Topstone 3", "Cannondale", Category.gravel, FrameSize.M, "sage", 2025, Condition.new, D("1490"), (7, 30), 2),
    ("Grizl 6", "Canyon", Category.gravel, FrameSize.M, "black", 2025, Condition.new, D("1749"), (7, 30), 1),
    ("Kids 20", "Woom", Category.kids, FrameSize.XS, "yellow", 2021, Condition.used, D("290"), (2, 12), 2),
    ("Kids 24", "Woom", Category.kids, FrameSize.XS, "red", 2021, Condition.used, D("350"), (2, 12), 1),
    ("Load 60", "Riese & Müller", Category.cargo, FrameSize.M, "grey", 2025, Condition.new, D("5800"), (40, 90), 1),
]
CODE_PART = {Category.city: "CITY", Category.ebike: "EBIKE", Category.mountain: "MTB", Category.road: "ROAD",
             Category.gravel: "GRAV", Category.kids: "KIDS", Category.cargo: "CARGO"}

# Seeded sale bikes with a planted listing date (P7); the others were listed 10–60 days ago
LISTED_DAYS_AGO = {"S-EBIKE-03": 100, "S-ROAD-02": 140, "S-EBIKE-02": 20, "S-MTB-02": 15}
SLOW_SELLER_EXPIRED_AFTER = {"S-ROAD-02": (30, 85)}   # days after listing, each reservation expired
POPULAR_VIEWS = {"S-EBIKE-03": 4}                     # weight in bike views; 1 for other bikes


# ---------------------------------------------------------------- calendar helpers

def is_open(day: date) -> bool:
    return day.weekday() in OPENING_HOURS and day not in HOLIDAYS


def next_open(day: date) -> date:
    while not is_open(day):
        day += timedelta(days=1)
    return day


def minutes(t) -> int:
    return t.hour * 60 + t.minute


def opens(day: date) -> int:
    return minutes(OPENING_HOURS[day.weekday()][0])


def closes(day: date) -> int:
    return minutes(OPENING_HOURS[day.weekday()][1])


def at_minute(day: date, minute: int) -> datetime:
    """`minute` minutes after midnight on `day`, Zurich time, as UTC."""
    return at(day, minute // 60, minute % 60)


def school_holiday(day: date) -> bool:
    return any((m1, d1) <= (day.month, day.day) <= (m2, d2) for (m1, d1), (m2, d2) in SCHOOL_HOLIDAYS)


def summer_saturday(day: date) -> bool:
    return day.weekday() == 5 and 5 <= day.month <= 9


def is_large_ebike(bike: Bike) -> bool:
    return bike.category == Category.ebike and bike.frame_size == FrameSize.L


def june_first(today: date) -> date:
    """The 1 June inside the period (P5)."""
    this_year = date(today.year, 6, 1)
    return this_year if this_year < today else date(today.year - 1, 6, 1)


def spike_day(first: date) -> date:
    """The newspaper-article day (P8): the first Tuesday from 14 April on."""
    day = date(first.year if first.month < 4 else first.year + 1, 4, 14)
    while day.weekday() != 1:
        day += timedelta(days=1)
    return day


# ---------------------------------------------------------------- the generator

@dataclass
class Guest:
    user: User
    busy: list          # (from, until) of their open rentals, to keep the limit of 3 at once


class History:
    """Builds the year in memory; `write()` stores it."""

    def __init__(self, db: Session, today: date):
        self.db = db
        self.rng = random.Random(RANDOM_SEED)
        self.today = today
        self.first = today - timedelta(days=DAYS)
        self.window_start = at_minute(self.first, 8 * 60)
        self.june = june_first(today)
        self.users: list[User] = []
        self.guests: list[Guest] = []
        self.weights: list[float] = []
        self.rentals: list[Rental] = []
        self.orders: list[Order] = []
        self.sold: list[Bike] = []
        self.sell_after: dict[str, int] = {}         # sold bike code -> days until it was reserved
        self.events: list[AnalyticsEvent] = []
        self.turned_away: list[date] = []            # summer Saturdays the L e-bikes were out (P2)
        self.bikes = {b.code: b for b in db.exec(select(Bike)).all()}

    # -------------------------------------------------------- customers

    def make_guests(self) -> None:
        password = AuthService()._hash_password(secrets.token_urlsafe(24))   # nobody knows it
        for n in range(1, GUESTS + 1):
            user = User(user_id=str(uuid.UUID(int=self.rng.getrandbits(128))), username=f"guest{n:03d}",
                        email=f"guest{n:03d}@bikeshop.test", hashed_password=password)
            self.users.append(user)
            self.guests.append(Guest(user, []))
            self.weights.append(1 / n ** 0.8)       # a few regulars, many one-off customers

    def pick_guest(self, created: datetime, until: datetime) -> User:
        """A customer with fewer than 3 rentals open between `created` and `until`."""
        for _ in range(20):
            guest = self.rng.choices(self.guests, self.weights)[0]
            if sum(1 for a, b in guest.busy if a < until and created < b) < 3:
                guest.busy.append((created, until))
                return guest.user
        guest = self.guests[-1]
        guest.busy.append((created, until))
        return guest.user

    # -------------------------------------------------------- rentals

    def start_chance(self, bike: Bike, day: date, progress: float) -> float:
        if bike.category == Category.kids:
            return .45 if school_holiday(day) else .006                          # P4
        if is_large_ebike(bike) and summer_saturday(day):
            return .97                                                          # P2
        chance = BASE_CHANCE[bike.category] * SEASON[day.month]                 # P1, P3
        if day.weekday() == 5:
            chance *= 2
        if bike.category == Category.gravel:
            chance *= .6 + 1.2 * progress                                       # P6
        return min(chance, .9)

    def period(self, bike: Bike, day: date) -> tuple[datetime, datetime] | None:
        """Pick-up and return for a rental starting on `day`, both within opening hours."""
        latest_start = 12 * 60 if day.weekday() == 5 else 15 * 60
        start_min = opens(day) + 15 * self.rng.randint(0, (latest_start - opens(day)) // 15)
        short, one_day = DURATION_MIX.get(bike.category, DEFAULT_MIX)
        kind = self.rng.random()
        if kind < short:                                       # a few hours, back the same day
            end_day = day
            end_min = min(start_min + 60 * self.rng.randint(1, 6), closes(day))
        elif kind < short + one_day:                           # back the next open day, same time
            end_day = next_open(day + timedelta(days=1))
            end_min = min(max(start_min, opens(end_day)), closes(end_day))
        else:                                                  # several days
            end_day = next_open(day + timedelta(days=self.rng.randint(2, MAX_DAYS.get(bike.category, 4))))
            end_min = opens(end_day) + 15 * self.rng.randint(0, (closes(end_day) - 30 - opens(end_day)) // 15)
        if end_day >= self.today:
            return None                                        # history ends yesterday
        return at_minute(day, start_min), at_minute(end_day, end_min)

    def booked_at(self, bike: Bike, start: datetime) -> datetime:
        """When the customer booked: online, some time before pick-up."""
        day = to_local(start).date()
        if is_large_ebike(bike) and summer_saturday(day):
            lead = self.rng.randint(5, 30)                     # popular: people book early (P2)
        elif self.rng.random() < .3:
            return max(start - timedelta(minutes=self.rng.randint(15, 120)), self.window_start)
        else:
            lead = min(21, int(self.rng.expovariate(1 / 5)) + 1)
        created = at_minute(day - timedelta(days=lead), self.rng.randint(7 * 60, 22 * 60))
        return max(created, self.window_start)

    def returned_at(self, start: datetime, end: datetime, picked: datetime) -> datetime:
        """Mostly on time or a bit early; some late the same day, a few the next open day."""
        local_end = to_local(end)
        r = self.rng.random()
        if r < .75:
            returned = max(end - timedelta(minutes=self.rng.randint(0, 45)), picked + timedelta(minutes=30))
        elif r < .95 and minutes(local_end) + 90 <= closes(local_end.date()):
            returned = end + timedelta(minutes=self.rng.randint(10, 90))
        else:
            next_day = next_open(local_end.date() + timedelta(days=1))
            returned = at_minute(next_day, opens(next_day) + self.rng.randint(5, 120))
        if to_local(returned).date() >= self.today:
            returned = end                                     # would be today: say on time
        return returned

    def rates(self, bike: Bike, created: datetime) -> tuple[Decimal, Decimal]:
        if bike.category == Category.ebike and to_local(created).date() < self.june:
            return EBIKE_RATES_BEFORE_JUNE                     # P5
        hourly, daily, _ = RATES[bike.category]
        return hourly, daily

    def make_rental(self, bike: Bike, start: datetime, end: datetime) -> datetime:
        """One returned rental (and sometimes a cancelled one before it). Returns when the bike is back."""
        created = self.booked_at(bike, start)
        hourly, daily = self.rates(bike, created)
        picked = start + timedelta(minutes=self.rng.randint(0, 20))
        returned = self.returned_at(start, end, picked)
        back = max(end, returned)
        self.rentals.append(Rental(
            bike_id=bike.id, user_id=self.pick_guest(created, back).user_id, start_at=start, end_at=end,
            status=RentalStatus.returned, hourly_chf=hourly, daily_chf=daily,
            quoted_price_chf=rental_price(start, end, hourly, daily).total_chf,
            picked_up_at=picked, returned_at=returned,
            final_price_chf=rental_price(start, back, hourly, daily).total_chf, created_at=created))
        if self.rng.random() < .07:
            # Someone else had booked the same slot earlier and cancelled it
            first_booking = max(created - timedelta(days=self.rng.randint(1, 5)), self.window_start)
            if first_booking < created:
                h, d = self.rates(bike, first_booking)
                self.rentals.append(Rental(
                    bike_id=bike.id, user_id=self.pick_guest(first_booking, first_booking).user_id,
                    start_at=start, end_at=end, status=RentalStatus.cancelled, hourly_chf=h, daily_chf=d,
                    quoted_price_chf=rental_price(start, end, h, d).total_chf, created_at=first_booking))
        return back

    def make_rentals(self) -> None:
        codes = [row[0] for row in RENTAL_BIKES]
        fleet = [self.bikes[c] for c in codes if c in self.bikes]
        taken = {}   # bike id -> (start, end) of rentals already in the database
        for r in self.db.exec(select(Rental).where(Rental.status != RentalStatus.cancelled)).all():
            taken.setdefault(r.bike_id, []).append((r.start_at, max(r.end_at, r.returned_at or r.end_at)))
        free_from = {bike.id: self.window_start for bike in fleet}
        for offset in range(DAYS):
            day = self.first + timedelta(days=offset)
            if not is_open(day):
                continue
            for bike in fleet:
                if self.rng.random() >= self.start_chance(bike, day, offset / DAYS):
                    continue
                times = self.period(bike, day)
                if not times or times[0] < free_from[bike.id]:
                    continue
                start, end = times
                if any(a < end + timedelta(days=1) and start < b for a, b in taken.get(bike.id, [])):
                    continue
                free_from[bike.id] = self.make_rental(bike, start, end)

    # -------------------------------------------------------- sales

    def order(self, bike: Bike, created: datetime, status: OrderStatus, closed: datetime) -> None:
        expires = created + timedelta(days=ORDER_HOLD_DAYS)
        self.orders.append(Order(bike_id=bike.id, user_id=self.pick_guest(created, closed).user_id,
                                 price_chf=bike.sale_price_chf, status=status, expires_at=expires,
                                 created_at=created, closed_at=closed))

    def online(self, day: date) -> datetime:
        return at_minute(day, self.rng.randint(7 * 60, 22 * 60))

    def make_sales(self) -> None:
        counters = {cat: 10 for cat in Category}
        for name, brand, cat, size, color, year, cond, price, (low, high), count in SOLD_BIKES:
            for _ in range(count):
                counters[cat] += 1
                days_to_sell = self.rng.randint(low, high)
                listed = self.first + timedelta(days=self.rng.randint(0, DAYS - days_to_sell - 10))
                bike = Bike(code=f"S-{CODE_PART[cat]}-{counters[cat]:02d}", name=name, brand=brand, category=cat,
                            frame_size=size, color=color, year=year, purpose=Purpose.sale, condition=cond,
                            sale_price_chf=price, status=BikeStatus.sold, description="",
                            created_at=at_minute(listed, 9 * 60))
                self.sold.append(bike)
                self.sell_after[bike.code] = days_to_sell

    def sell(self, bike: Bike) -> None:
        """The orders of a sold bike: sometimes a reservation that expired, then the one that was collected."""
        listed = to_local(bike.created_at).date()
        days_to_sell = self.sell_after[bike.code]
        reserve_day = listed + timedelta(days=days_to_sell)
        if days_to_sell >= 12 and self.rng.random() < .3:
            first = self.online(reserve_day - timedelta(days=10))
            expired = first + timedelta(days=ORDER_HOLD_DAYS, minutes=self.rng.randint(1, 14))
            self.order(bike, first, OrderStatus.expired, expired)
        created = self.online(reserve_day)
        pick_up = next_open(reserve_day + timedelta(days=self.rng.randint(1, 4)))
        closed = at_minute(pick_up, opens(pick_up) + 15 * self.rng.randint(4, 20))
        closed = min(closed, created + timedelta(days=ORDER_HOLD_DAYS, hours=-1))
        self.order(bike, created, OrderStatus.completed, closed)
        bike.updated_at = closed

    def backdate_seeded_bikes(self) -> None:
        """Seeded bikes were 'created' today; give them a past (P7)."""
        for code, *_ in RENTAL_BIKES:
            if code in self.bikes and self.bikes[code].created_at > self.window_start:
                self.bikes[code].created_at = self.window_start - timedelta(days=30)
        for code, *_ in SALE_BIKES:
            bike = self.bikes.get(code)
            if not bike or bike.created_at < self.window_start:
                continue
            listed = self.today - timedelta(days=LISTED_DAYS_AGO.get(code, self.rng.randint(10, 60)))
            bike.created_at = at_minute(listed, 9 * 60)
            for after in SLOW_SELLER_EXPIRED_AFTER.get(code, ()):
                created = self.online(listed + timedelta(days=after))
                self.order(bike, created, OrderStatus.expired,
                           created + timedelta(days=ORDER_HOLD_DAYS, minutes=self.rng.randint(1, 14)))

    # -------------------------------------------------------- analytics

    def make_events(self) -> None:
        def event(day, name, bike=None):
            self.events.append(AnalyticsEvent(day=day, name=name, bike_id=bike.id if bike else None,
                                              category=bike.category.value if bike else None))

        by_id = {b.id: b for b in list(self.bikes.values()) + self.sold}
        booked, reserved = {}, {}
        for r in self.rentals:
            booked.setdefault(to_local(r.created_at).date(), []).append(by_id[r.bike_id])
        for o in self.orders:
            reserved.setdefault(to_local(o.created_at).date(), []).append(by_id[o.bike_id])

        rental_fleet = [b for b in self.bikes.values() if b.purpose == Purpose.rental]
        large_ebikes = [b for b in rental_fleet if is_large_ebike(b)]
        sold_on = {o.bike_id: to_local(o.closed_at).date() for o in self.orders if o.status == OrderStatus.completed}
        spike = spike_day(self.first)
        out_on = {to_local(r.start_at).date() for r in self.rentals
                  if r.status == RentalStatus.returned and by_id[r.bike_id] in large_ebikes}

        for offset in range(DAYS):
            day = self.first + timedelta(days=offset)
            weekday = {5: 1.8, 6: .8}.get(day.weekday(), 1.0)
            traffic = 22 * SEASON[day.month] * weekday * self.rng.uniform(.8, 1.2)
            on_sale = [b for b in by_id.values() if b.purpose == Purpose.sale
                       and to_local(b.created_at).date() <= day and sold_on.get(b.id, self.today) >= day
                       and b.status != BikeStatus.retired]
            browsable = rental_fleet + on_sale
            view_weights = [POPULAR_VIEWS.get(b.code, 1) for b in browsable]

            for _ in range(round(traffic * (6 if day == spike else 1))):          # P8
                event(day, "catalogue_view")
            for bike in self.rng.choices(browsable, view_weights, k=round(traffic * .7)):
                event(day, "bike_view", bike)
            for bike in self.rng.choices(rental_fleet, k=round(traffic * .1)):
                event(day, "quote", bike)
            for bike in booked.get(day, []):
                event(day, "catalogue_view")
                for _ in range(self.rng.randint(2, 5)):
                    event(day, "bike_view", bike)
                for _ in range(self.rng.randint(1, 4)):
                    event(day, "quote", bike)
                event(day, "booking", bike)
            for bike in reserved.get(day, []):
                for _ in range(self.rng.randint(3, 6)):
                    event(day, "bike_view", bike)
                event(day, "reservation", bike)
            # P2: on summer weekends the large e-bikes are gone; people quote and don't book
            saturday = day + timedelta(days=(5 - day.weekday()) % 7)
            if day.weekday() in (4, 5) and summer_saturday(saturday) and saturday in out_on:
                for _ in range(self.rng.randint(4, 9)):
                    event(day, "quote", self.rng.choice(large_ebikes))

    # -------------------------------------------------------- write

    def build_and_write(self) -> None:
        self.make_guests()
        self.backdate_seeded_bikes()
        self.make_rentals()
        self.make_sales()
        self.db.add_all(self.sold)
        self.db.flush()                     # the sold bikes get their ids
        for bike in self.sold:
            self.sell(bike)
        self.make_events()

        # Each guest signed up just before their first booking
        first_seen = {}
        for row in self.rentals + self.orders:
            first_seen[row.user_id] = min(first_seen.get(row.user_id, row.created_at), row.created_at)
        for user in self.users:
            seen = first_seen.get(user.user_id, self.window_start + timedelta(days=self.rng.randint(0, DAYS - 1)))
            user.created_at = seen - timedelta(minutes=self.rng.randint(5, 60))

        self.db.add_all(self.users + self.rentals + self.orders + self.events + list(self.bikes.values()))
        self.db.commit()
        print(f"  {len(self.users)} customers, {len(self.rentals)} rentals, {len(self.sold)} bikes sold, "
              f"{len(self.orders)} orders, {len(self.events)} analytics events")


def main() -> None:
    init_database()
    with Session(engine) as db:
        print("Seeding a year of history:")
        if db.exec(select(User).where(User.username == "guest001")).first():
            print("  history exists, skipped")
            return
        if not db.exec(select(Bike).where(Bike.code == RENTAL_BIKES[0][0])).first():
            raise SystemExit("Run python -m scripts.seed first: the history needs the seeded bikes.")
        History(db, to_local(utcnow()).date()).build_and_write()
    print("Done.")


if __name__ == "__main__":
    main()
