"""
Data for the Workshop (SPEC §14.12): more bikes, more rentals with short gaps,
bookings ahead, fictional suppliers, scans, and ten planted cases.

    python -m scripts.seed_workshop      # after scripts.seed and scripts.seed_history

The planted cases D1-D10 are the answer key: an agent that reasons well should
reach the answers in SPEC §14.12. All dates count from the day this runs, so run
it close to the demo. It runs once: if suppliers exist, it does nothing.

It only adds rows. seed.py and seed_history.py don't change, and every rental
follows the shop's rules (opening hours, 15-minute grid, no double booking).
"""
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from api.database import engine, init_database
from api.models.models import (
    AnalyticsEvent, Bike, BikeFinance, BikeStatus, Category, Condition, FrameSize, PartOffer, Purpose, Rental,
    RentalRate, RentalStatus, Supplier, User, WorkshopCase, WorkshopScan,
)
from api.services import scan_service, workshop_service as shop
from api.services.pricing_service import money, rental_price
from api.timeutils import to_local, utcnow
from scripts.seed_history import at_minute, closes, is_open, opens

D = Decimal
RANDOM_SEED = 2027
ALL = [c.value for c in Category]
ELECTRIC = ["ebike", "cargo"]

# code, name, brand, category, size, color, year, description
NEW_RENTAL_BIKES = [
    ("R-CITY-05", "FX 2", "Trek", Category.city, FrameSize.M, "grey", 2023, "Light hybrid, disc brakes."),
    ("R-CITY-06", "Escape 3", "Giant", Category.city, FrameSize.L, "black", 2022, "Simple 8-speed city bike."),
    ("R-CITY-07", "Touring One", "Cube", Category.city, FrameSize.M, "silver", 2017, "An old faithful, full mudguards."),
    ("R-CITY-08", "Image 3", "Kalkhoff", Category.city, FrameSize.S, "blue", 2024, "Low step-in, belt-free 7-speed."),
    ("R-EBIKE-06", "Kathmandu Hybrid", "Cube", Category.ebike, FrameSize.L, "green", 2024, "Touring e-bike, 750 Wh."),
    ("R-EBIKE-07", "Allant+ 7", "Trek", Category.ebike, FrameSize.M, "red", 2023, "Commuter e-bike, 625 Wh."),
    ("R-EBIKE-08", "Explore E+ 2", "Giant", Category.ebike, FrameSize.L, "teal", 2023, "All-road e-bike, 500 Wh."),
    ("R-EBIKE-09", "ST1", "Stromer", Category.ebike, FrameSize.M, "white", 2018, "An early Stromer, still quick."),
    ("R-EBIKE-10", "Gotour 4", "Flyer", Category.ebike, FrameSize.S, "white", 2024, "Comfortable, low step-in."),
    ("R-EBIKE-11", "Endeavour 5", "Kalkhoff", Category.ebike, FrameSize.L, "anthracite", 2024, "Long-range tourer."),
    ("R-MTB-04", "Marlin 7", "Trek", Category.mountain, FrameSize.M, "orange", 2023, "Hardtail for easy trails."),
    ("R-MTB-05", "Aspect 940", "Scott", Category.mountain, FrameSize.L, "black", 2023, "Hardtail, 29 inch wheels."),
    ("R-MTB-06", "Stereo 120", "Cube", Category.mountain, FrameSize.M, "blue", 2024, "Full suspension trail bike."),
    ("R-ROAD-03", "Contend 2", "Giant", Category.road, FrameSize.M, "grey", 2023, "Endurance road bike."),
    ("R-ROAD-04", "Domane AL 4", "Trek", Category.road, FrameSize.L, "red", 2023, "Comfortable aluminium road bike."),
    ("R-GRAV-03", "Grizl 6", "Canyon", Category.gravel, FrameSize.M, "black", 2024, "Gravel bike with rack mounts."),
    ("R-GRAV-04", "Checkpoint ALR 4", "Trek", Category.gravel, FrameSize.L, "green", 2023, "Gravel all-rounder."),
    ("R-GRAV-05", "Revolt 2", "Giant", Category.gravel, FrameSize.S, "sand", 2024, "Light gravel bike."),
    ("R-KIDS-03", "Woom 5", "Woom", Category.kids, FrameSize.XS, "purple", 2024, "For kids about 7 to 11 years old."),
    ("R-CARGO-03", "Family", "Urban Arrow", Category.cargo, FrameSize.M, "black", 2023, "Electric box bike, three kids."),
]

PURCHASE = {Category.city: 900, Category.ebike: 3800, Category.mountain: 1500, Category.road: 1700,
            Category.gravel: 1600, Category.kids: 500, Category.cargo: 5200}

# All fictional (SPEC §14.12): name, country, kind, shipping. The last one is the shop's own shelf.
SUPPLIERS = [
    ("Aarewerk Veloteile AG", "Switzerland", "oem", 9), ("Jura Bikeparts GmbH", "Switzerland", "aftermarket", 12),
    ("Rheintal Radteile GmbH", "Germany", "oem", 18), ("Bodensee Zweirad KG", "Austria", "aftermarket", 16),
    ("Lombarda Ciclo Ricambi", "Italy", "aftermarket", 20), ("Moravia Cyklo Dily", "Czechia", "aftermarket", 22),
    ("Pearl River Cycle Supply", "China", "aftermarket", 35), ("Keelung Bicycle Components", "Taiwan", "oem", 40),
    ("Zweites Leben Velo", "Switzerland", "second_hand", 8), ("BikeShop's own shelf", "Switzerland", "oem", 0),
]
# supplier index, price factor, delivery days, quality
TIERS = [(0, 1.35, 2, "new_oem"), (1, 1.0, 3, "new_aftermarket"), (2, 1.1, 5, "new_oem"), (3, .95, 6, "new_aftermarket"),
         (4, .85, 8, "new_aftermarket"), (5, .8, 9, "new_aftermarket"), (6, .5, 16, "new_aftermarket"),
         (7, .75, 12, "new_oem"), (8, .6, 1, "used")]

# Small parts the shop keeps on its own shelf: there today, at list price
ON_THE_SHELF = {"brake_pads_front", "brake_pads_rear", "chain", "tyre_front", "tyre_rear", "cables"}

# part, label, fits, price CHF, mechanic hours, safety part
PARTS = [
    ("frame", "Replacement frame", ALL, 780, 8, True), ("fork", "Fork", ALL, 260, 6, True),
    ("headset", "Headset", ALL, 45, 2, True), ("wheel_front", "Front wheel", ALL, 190, 2, True),
    ("wheel_rear", "Rear wheel", ALL, 240, 2.5, True), ("tyre_front", "Front tyre", ALL, 42, .5, True),
    ("tyre_rear", "Rear tyre", ALL, 42, .5, True), ("hub_bearing_front", "Front hub bearings", ALL, 38, 1.5, True),
    ("hub_bearing_rear", "Rear hub bearings", ALL, 48, 2, True), ("bottom_bracket", "Bottom bracket", ALL, 42, 2, True),
    ("crank", "Crank set", ALL, 120, 1.5, True), ("pedals", "Pedals", ALL, 35, .25, False),
    ("chain", "Chain", ALL, 32, .5, True), ("cassette", "Cassette", ALL, 58, .75, True),
    ("chainring", "Chainring", ALL, 49, 1, False), ("rear_derailleur", "Rear derailleur", ALL, 85, 1, False),
    ("brake_pads_front", "Front brake pads", ALL, 24, .5, True), ("brake_pads_rear", "Rear brake pads", ALL, 24, .5, True),
    ("brake_rotor_front", "Front brake rotor", ALL, 46, .75, True), ("brake_rotor_rear", "Rear brake rotor", ALL, 46, .75, True),
    ("brake_caliper_front", "Front brake caliper", ALL, 110, 1.5, True), ("brake_caliper_rear", "Rear brake caliper", ALL, 110, 1.5, True),
    ("cables", "Cable set", ALL, 28, 1.5, True), ("stem", "Stem", ALL, 48, .5, True), ("handlebar", "Handlebar", ALL, 62, 1, True),
    ("seatpost", "Seatpost", ALL, 44, .25, True), ("saddle", "Saddle", ALL, 38, .25, False), ("grips", "Grips", ALL, 18, .25, False),
    ("lights", "Light set", ALL, 65, .75, True), ("kickstand", "Kickstand", ALL, 22, .25, False),
    ("battery", "Battery", ELECTRIC, 1020, 1, True), ("motor", "Motor", ELECTRIC, 880, 3, False),
    ("controller", "Controller and sensors", ELECTRIC, 310, 1.5, False), ("wiring", "Wiring loom", ELECTRIC, 95, 2, True),
]


def fault(value) -> dict:
    return {"value": value}


# The planted cases, the answer key (SPEC §14.12): bike -> what the machine will find
PLANTED = {
    "R-EBIKE-08": {"frame_crack_down_tube": fault(1.2)},                                    # D1
    "R-CITY-05": {"pad_rear_laser": fault(.6), "pad_rear_camera": fault(.62)},               # D2
    "R-MTB-04": {"hub_play_rear": fault(.16), "hub_noise_rear": fault(31)},                  # D3, moves fast (below)
    "R-ROAD-03": {"rim_crack_rear": fault(.7)},                                              # D4
    "R-EBIKE-09": {"battery_health": fault(52), "cell_gap_3": fault(180), "cell_gap_7": fault(145)},   # D5
    "R-GRAV-03": {"pad_front_laser": fault(.7), "pad_front_camera": fault(.72), "rotor_thickness_front": fault(1.4)},   # D6
    "R-CITY-06": {"fork_crack_left": fault(.7), "rim_crack_front": fault(.6), "headset_play": fault(1.0)},   # D7, first bike
    "R-ROAD-04": {"bb_play": fault(.7), "crank_crack_right": fault(.6)},                     # D7, second bike
    "R-GRAV-04": {"brake_force_front": fault(60), "caliper_stick_front": fault(60)},         # D8
    "R-CARGO-03": {"hub_play_front": fault(.6)},                                             # D9
    "R-CITY-07": {"chain_stretch": fault(.6), "tyre_tread_rear": fault(.9)},                 # D10
}
TREND_HISTORY = {"R-MTB-04": {"hub_play_rear": [.06, .09], "hub_noise_rear": [23, 26]}}      # D3: the earlier scans

# Returned recently, not scanned yet: for the live scan (SPEC §14.2)
WAITING = {"R-EBIKE-10": {"pad_front_laser": fault(.7), "pad_front_camera": fault(.72)},
           "R-CITY-08": {"chain_stretch": fault(.55)}, "R-MTB-05": {}}

# Bikes with little use, so a repair costs more than they earn (D5, D10)
QUIET = {"R-EBIKE-09", "R-CITY-07"}
FINANCE = {"R-EBIKE-09": (3600, 700, 1100), "R-CITY-07": (850, 300, 640)}   # purchase, book, market
KEEP_FREE = {"R-EBIKE-03", "R-CITY-03", "R-MTB-01"}   # the demo customer can always book these next week


class Workshop:
    def __init__(self, db: Session, today: date):
        self.db, self.today, self.now = db, today, utcnow()
        self.rng = random.Random(RANDOM_SEED)
        self.bikes: dict[str, Bike] = {}
        self.taken: dict[int, list] = {}
        self.guests, self.open_count, self.new_rentals, self.events = [], {}, [], []

    # -------------------------------------------------------- calendar

    def open_after(self, n: int) -> date:
        """The n-th open day after today (1 = the next one)."""
        day = self.today
        for _ in range(n):
            day = shop.next_open(day + timedelta(days=1))
        return day

    def open_before(self, n: int) -> date:
        day = self.today
        while n:
            day -= timedelta(days=1)
            n -= is_open(day)
        return day

    # -------------------------------------------------------- bikes, money, parts

    def add_bikes(self) -> None:
        for code, name, brand, cat, size, color, year, desc in NEW_RENTAL_BIKES:
            self.db.add(Bike(code=code, name=name, brand=brand, category=cat, frame_size=size, color=color, year=year,
                             purpose=Purpose.rental, condition=Condition.used, description=desc,
                             created_at=self.now - timedelta(days=90)))
        self.db.flush()
        self.bikes = {b.code: b for b in self.db.exec(select(Bike)).all()}
        for bike in self.db.exec(select(Bike)).all():
            base = D(PURCHASE[bike.category])
            age = max(self.today.year - bike.year, 0)
            purchase, book, market = FINANCE.get(bike.code, (
                base, base * max(D("0.2"), 1 - D("0.15") * age), base * max(D("0.15"), D("0.85") - D("0.12") * age)))
            self.db.add(BikeFinance(bike_id=bike.id, purchase_chf=money(D(purchase)), book_value_chf=money(D(book)),
                                    market_value_chf=money(D(market))))

    def add_suppliers(self) -> None:
        suppliers = [Supplier(name=n, country=c, kind=k, shipping_chf=D(s)) for n, c, k, s in SUPPLIERS]
        self.db.add_all(suppliers)
        self.db.flush()
        for part, label, fits, price, hours, safety in PARTS:
            if part in ON_THE_SHELF:
                self.db.add(PartOffer(part=part, label=label, fits=fits, supplier_id=suppliers[-1].id,
                                      price_chf=money(D(str(price))), delivery_days=0, quality="new_oem",
                                      safety_part=safety, repair_hours=D(str(hours))))
            keep = {0, 6, 8} | set(self.rng.sample(range(1, 8), 3))     # always fast, cheap and used
            for n, (index, factor, days, quality) in enumerate(TIERS):
                if n in keep:
                    self.db.add(PartOffer(part=part, label=label, fits=fits, supplier_id=suppliers[index].id,
                                          price_chf=money(D(str(price)) * D(str(factor))), delivery_days=days,
                                          quality=quality, safety_part=safety, repair_hours=D(str(hours))))

    # -------------------------------------------------------- rentals

    def load_taken(self) -> None:
        for r in self.db.exec(select(Rental).where(Rental.status != RentalStatus.cancelled)).all():
            self.taken.setdefault(r.bike_id, []).append((r.start_at, max(r.end_at, r.returned_at or r.end_at)))
            if r.status in (RentalStatus.booked, RentalStatus.active):
                self.open_count[r.user_id] = self.open_count.get(r.user_id, 0) + 1
        cutoff = self.now - timedelta(days=70)
        self.guests = self.db.exec(select(User).where(User.username.like("guest%"), User.created_at < cutoff)).all()

    def free(self, bike: Bike, start: datetime, end: datetime) -> bool:
        return all(not (a < end and start < b) for a, b in self.taken.get(bike.id, []))

    def guest(self) -> User:
        """A customer with fewer than 3 open rentals (SPEC §5.5)."""
        for _ in range(400):
            user = self.rng.choice(self.guests)
            if self.open_count.get(user.user_id, 0) < 3:
                return user
        raise SystemExit("Not enough invented customers for the bookings.")

    def rental(self, bike: Bike, start: datetime, end: datetime, user: User | None = None,
               returned: datetime | None = None) -> Rental:
        """One rental following the shop's rules: returned if it has `returned`, else booked ahead."""
        rate = self.db.get(RentalRate, bike.category)
        user = user or self.guest()
        future = start > self.now
        created = (self.now - timedelta(days=self.rng.randint(1, 14))) if future else start - timedelta(days=self.rng.randint(1, 10))
        back = max(end, returned) if returned else None
        rental = Rental(bike_id=bike.id, user_id=user.user_id, start_at=start, end_at=end,
                        status=RentalStatus.returned if returned else RentalStatus.booked,
                        hourly_chf=rate.hourly_chf, daily_chf=rate.daily_chf,
                        quoted_price_chf=rental_price(start, end, rate.hourly_chf, rate.daily_chf).total_chf,
                        picked_up_at=start if returned else None, returned_at=returned,
                        final_price_chf=rental_price(start, back, rate.hourly_chf, rate.daily_chf).total_chf if back else None,
                        created_at=created)
        self.db.add(rental)
        self.taken.setdefault(bike.id, []).append((start, back or end))
        if future:
            self.open_count[user.user_id] = self.open_count.get(user.user_id, 0) + 1
        self.new_rentals.append(rental)
        self.events.append(AnalyticsEvent(day=to_local(created).date(), name="booking", bike_id=bike.id,
                                          category=bike.category.value))
        return rental

    def same_day(self, bike: Bike, day: date, start_hour: int, hours: int, user: User | None = None,
                 returned: bool = False) -> Rental:
        start = at_minute(day, start_hour * 60)
        end_minute = min(start_hour * 60 + hours * 60, closes(day))
        end = at_minute(day, end_minute)
        return self.rental(bike, start, end, user, end if returned else None)

    def planted_rentals(self, customer: User) -> None:
        """The bookings that make each planted case hard (SPEC §14.12)."""
        b = self.bikes
        # Every planted bike came back three open days ago, which the scan belongs to
        for code in PLANTED:
            self.same_day(b[code], self.open_before(3), 10, 5, returned=True)
        self.same_day(b["R-EBIKE-08"], self.open_after(1), 10, 5, customer)       # D1: pick-up on the next open day
        self.same_day(b["R-EBIKE-08"], self.open_after(4), 10, 4)
        self.same_day(b["R-CITY-05"], self.open_after(2), 10, 4)                   # D2
        self.same_day(b["R-MTB-04"], self.open_after(3), 10, 5)                    # D3
        self.same_day(b["R-ROAD-03"], self.open_after(6), 9, 6)                    # D4: a fast part makes it, a cheap one doesn't
        self.same_day(b["R-EBIKE-09"], self.open_after(5), 10, 4)                  # D5
        self.same_day(b["R-GRAV-03"], self.open_after(3), 10, 5)                   # D6
        self.same_day(b["R-ROAD-04"], self.open_after(3), 10, 5)                   # D7: the mechanic is busy until then
        self.same_day(b["R-GRAV-04"], self.open_after(3), 10, 5)                   # D8
        self.same_day(b["R-CARGO-03"], self.open_after(1), 10, 5)                  # D9
        for code in ("R-CARGO-01", "R-CARGO-02"):                                  # D9: no other cargo bike is free
            day = self.open_after(1)
            if self.free(b[code], at_minute(day, 9 * 60), at_minute(day, 15 * 60)):
                self.same_day(b[code], day, 9, 6)
        self.same_day(b["R-CITY-07"], self.open_after(5), 13, 3)                   # D10
        # The bikes waiting for a scan came back on the last open day
        for code in WAITING:
            self.same_day(b[code], self.open_before(1), 9, 6, returned=True)
        self.same_day(b["R-EBIKE-10"], self.open_after(2), 10, 5)                  # the live scan finds a real problem

    def fill(self, bike: Bike, first: date, last: date, chance: float) -> None:
        """Rentals one after the other with gaps of hours: the reason the shop needs this tool."""
        day, returned = first, first < self.today
        while day <= last:
            if not is_open(day) or self.rng.random() > chance:
                day += timedelta(days=1)
                continue
            start = at_minute(day, opens(day) + 15 * self.rng.randint(0, 12))
            if self.rng.random() < .6:      # back the same day, the next customer that afternoon
                end_day = day
                end = at_minute(day, min(to_local(start).hour * 60 + 60 * self.rng.randint(2, 5), closes(day)))
            else:                           # a day or two, back in the morning
                end_day = shop.next_open(day + timedelta(days=self.rng.randint(1, 2)))
                end = at_minute(end_day, opens(end_day) + 15 * self.rng.randint(0, 16))
            if end_day <= last and end > start + timedelta(hours=1) and self.free(bike, start, end + timedelta(hours=2)):
                self.rental(bike, start, end, returned=end if returned else None)
            day = end_day if end_day > day else day + timedelta(days=1)   # often the same day it came back

    def add_rentals(self) -> None:
        new = [row[0] for row in NEW_RENTAL_BIKES]
        for code in new:                                              # the last 8 weeks, for the new bikes
            bike = self.bikes[code]
            if code in QUIET or bike.category in (Category.kids, Category.cargo):
                continue
            self.fill(bike, self.today - timedelta(days=56), self.open_before(5),
                      .5 if bike.category == Category.gravel else .4)
        active = {r.bike_id for r in self.db.exec(select(Rental).where(Rental.status == RentalStatus.active)).all()}
        for code, bike in self.bikes.items():                         # bookings ahead, for the whole fleet
            if bike.purpose != Purpose.rental or bike.status != BikeStatus.available or bike.id in active or code in QUIET:
                continue
            start = self.open_after(1)
            if code in KEEP_FREE:
                start = self.today + timedelta(days=12)
            elif code in PLANTED:           # only the planted bookings at first: they define the case
                start = self.open_after(7)
            self.fill(bike, start, self.today + timedelta(days=55), .22)

    # -------------------------------------------------------- scans

    def scan_row(self, bike: Bike, rental: Rental, hours: float, faults: dict, previous: list | None, n: int) -> WorkshopScan:
        readings = scan_service.grade(scan_service.measure(bike, hours, faults, n), previous)
        return WorkshopScan(bike_id=bike.id, rental_id=rental.id, status="done", readings=readings, faults=faults,
                            verdict=scan_service.verdict(readings),
                            scanned_at=rental.returned_at + timedelta(hours=1))

    def add_scans(self) -> None:
        self.db.flush()
        returned = self.db.exec(select(Rental).where(Rental.status == RentalStatus.returned)
                                .order_by(Rental.returned_at)).all()
        by_bike: dict[int, list[Rental]] = {}
        for r in returned:
            by_bike.setdefault(r.bike_id, []).append(r)
        for code, bike in self.bikes.items():
            if bike.purpose != Purpose.rental or bike.id not in by_bike:
                continue
            rentals = by_bike[bike.id]
            total = scan_service.hours_used(self.db, bike.id)
            if code in WAITING:
                self.db.add(WorkshopScan(bike_id=bike.id, rental_id=rentals[-1].id, status="waiting", faults=WAITING[code]))
                rentals = rentals[:-1]
            previous, last = None, None
            chosen = rentals[-4:]
            for n, rental in enumerate(chosen):
                newest = n == len(chosen) - 1
                faults = dict(PLANTED.get(code, {})) if newest else {}
                earlier = TREND_HISTORY.get(code, {})
                steps_back = len(chosen) - 2 - n
                if not newest:
                    faults = {k: fault(values[-1 - steps_back]) for k, values in earlier.items() if steps_back < len(values)}
                last = self.scan_row(bike, rental, max(total - 8 * (len(chosen) - 1 - n), 0), faults, previous, n)
                previous = last.readings
                self.db.add(last)
            self.db.flush()
            if code in PLANTED and last:
                self.db.add(WorkshopCase(bike_id=bike.id, scan_id=last.id, stage=shop.OPEN))
            elif last and last.verdict != scan_service.FIT:
                raise SystemExit(f"{code}: normal wear should be fit, got {last.verdict}.")

    # -------------------------------------------------------- D7: the mechanic is already booked

    def busy_mechanic(self) -> None:
        """The first D7 bike has an approved plan, so its hours fill the mechanic's week."""
        self.db.flush()
        bike = self.bikes["R-CITY-06"]
        case = self.db.exec(select(WorkshopCase).where(WorkshopCase.bike_id == bike.id)).one()
        offers = []
        for part in ("fork", "wheel_front", "headset"):
            offers.append(min((o for o in shop.offers_for(self.db, bike, part) if o.quality == "new_oem"),
                              key=lambda o: o.delivery_days).id)
        case.stage = shop.ANALYSING
        answer = shop.submit_brief(self.db, case, {
            "verdict_sentence": "Not safe to rent: the fork and the front rim have cracks.",
            "what_is_wrong": "The left fork leg and the front rim have cracks, and the steering is loose.",
            "options": [{"kind": "repair", "title": "Replace fork, wheel, headset", "what_we_do": "New parts, fitted by our mechanic.", "offer_ids": offers},
                        {"kind": "scrap", "title": "Scrap the bike", "what_we_do": "Take it out of the fleet for parts."}],
            "recommended": "A", "recommended_why": "The repair is worth it on a bike this young."})
        assert answer.get("ok"), answer
        case.chosen_option, case.stage, case.agent_agreed = "A", shop.PLANNING, True
        answer = shop.submit_plan(self.db, case, {
            "summary": "New fork, front wheel and headset. Seeded, not written by the AI.",
            "steps": ["Order the parts", "Fit them", "Rescan"], "booking_actions": []})
        assert answer.get("ok"), answer
        case.stage = shop.APPROVED
        case.repair_hours = D(case.plan["repair_hours"])
        case.repair_day = date.fromisoformat(case.plan["repair_starts"])
        case.ready_estimate = date.fromisoformat(case.plan["ready_date"])
        bike.status = BikeStatus.maintenance
        self.db.add(case)
        self.db.add(bike)

    def run(self) -> None:
        self.add_bikes()
        self.add_suppliers()
        self.load_taken()
        customer = self.db.exec(select(User).where(User.username == "customer")).one()
        self.planted_rentals(customer)
        self.add_rentals()
        self.add_scans()
        self.busy_mechanic()
        self.db.add_all(self.events)
        self.db.commit()
        rentals = self.new_rentals
        print(f"  {len(NEW_RENTAL_BIKES)} bikes, {len(SUPPLIERS)} suppliers, {len(rentals)} rentals "
              f"({sum(r.status == RentalStatus.booked for r in rentals)} booked ahead)")


def main() -> None:
    init_database()
    with Session(engine) as db:
        print("Seeding the Workshop:")
        if db.exec(select(Supplier)).first():
            print("  workshop data exists, skipped")
            return
        if not db.exec(select(User).where(User.username == "guest001")).first():
            raise SystemExit("Run python -m scripts.seed and scripts.seed_history first.")
        Workshop(db, to_local(utcnow()).date()).run()
    print("Done.")


if __name__ == "__main__":
    main()
