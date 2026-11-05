"""
The diagnostic machine (SPEC §14.2) and the safety gate (§14.3).

The machine is fictional: lasers, ultrasound, cameras and test robots that
measure every part of a bike. Here that is plain code. A scan takes no AI call,
so a live scan is quick and can't use up the AI's limits.

- `CATALOGUE` lists what the machine measures, about 180 readings in 12 groups.
- `measure()` makes up the values: wear grows with the bike's hours of use, and
  a bike's hidden faults (`WorkshopScan.faults`) override single readings.
- `grade()` and `verdict()` are the SAFETY GATE. They compare readings with
  fixed limits, and the agent can't change what they say.
"""
import random
from typing import Optional

from sqlmodel import Session, select

from ..models.models import Bike, Category, Purpose, Rental, RentalStatus, WorkshopScan
from ..timeutils import utcnow
from .errors import NotFound

FIT, WATCH, UNFIT = "fit", "watch", "unfit"
OK, TREND = "ok", "trend"                 # a reading's status: ok | trend | watch | unfit

HOURS_TO_WEAR_OUT = 800                   # hours of use until normal wear nears a watch limit
MOST_NORMAL_WEAR = 0.6                    # normal wear alone never reaches a limit
TREND_SHARE = 0.3                         # moved this share of the way to the watch limit since the last scan

ELECTRIC = (Category.ebike, Category.cargo)

GROUP_LABELS = {
    "frame": "Frame", "fork": "Fork and headset", "wheels": "Wheels", "tyres": "Tyres",
    "hubs": "Hub bearings", "bottom_bracket": "Bottom bracket and cranks", "drivetrain": "Chain and gears",
    "brakes": "Brakes", "controls": "Cables and controls", "contact": "Saddle, bars and lights",
    "battery": "Battery", "motor": "Motor and electronics",
}


def _reading(group, key, name, unit, method, nominal, watch, unfit, part, safety=False):
    """One thing the machine measures. A limit below `nominal` means low values are the bad ones."""
    return {"group": group, "key": key, "name": name, "unit": unit, "method": method, "nominal": nominal,
            "watch": watch, "unfit": unfit, "part": part, "safety": safety}


def _catalogue() -> list[dict]:
    r = []
    # Frame: cracks found by ultrasound, zone by zone
    for zone in ("head tube", "down tube", "seat tube", "top tube", "left chainstay", "right chainstay",
                 "left seatstay", "right seatstay", "left dropout", "right dropout", "bottom bracket shell",
                 "seat cluster"):
        slug = zone.replace(" ", "_")
        r.append(_reading("frame", f"frame_crack_{slug}", f"Crack depth, {zone}", "mm", "ultrasound",
                          0.0, 0.3, 0.8, "frame", True))
        r.append(_reading("frame", f"frame_corrosion_{slug}", f"Corrosion, {zone}", "%", "multispectral camera",
                          1.0, 15, 35, "frame", True))
    r.append(_reading("frame", "frame_rear_alignment", "Rear triangle out of line", "mm", "laser", 0.3, 2.5, 5, "frame", True))
    r.append(_reading("frame", "frame_head_angle", "Head angle off", "degrees", "laser", 0.1, 0.8, 1.5, "frame", True))

    # Fork and headset
    for side in ("left", "right"):
        r.append(_reading("fork", f"fork_crack_{side}", f"Crack depth, {side} fork leg", "mm", "ultrasound", 0.0, 0.2, 0.5, "fork", True))
        r.append(_reading("fork", f"fork_alignment_{side}", f"{side.title()} fork leg out of line", "mm", "laser", 0.2, 2, 4, "fork", True))
    r.append(_reading("fork", "fork_crack_crown", "Crack depth, fork crown", "mm", "ultrasound", 0.0, 0.2, 0.5, "fork", True))
    r.append(_reading("fork", "fork_crack_steerer", "Crack depth, steerer", "mm", "ultrasound", 0.0, 0.2, 0.5, "fork", True))
    r.append(_reading("fork", "headset_play", "Headset play", "mm", "load robot", 0.05, 0.4, 0.9, "headset", True))
    r.append(_reading("fork", "headset_noise", "Headset bearing noise", "dB", "acoustic sensor", 22, 40, 55, "headset"))
    r.append(_reading("fork", "headset_torque", "Steering stiffness", "Nm", "torque robot", 0.2, 0.9, 1.6, "headset"))
    r.append(_reading("fork", "headset_corrosion", "Headset corrosion", "%", "multispectral camera", 1, 20, 45, "headset"))

    # Wheels, tyres and hub bearings, front and rear
    for end in ("front", "rear"):
        for quarter in (1, 2, 3, 4):
            r.append(_reading("wheels", f"spoke_tension_{end}_{quarter}", f"Spoke tension spread, {end} wheel, quarter {quarter}",
                              "%", "tension robot", 6, 20, 35, f"wheel_{end}", True))
        r.append(_reading("wheels", f"rim_lateral_{end}", f"Rim wobble sideways, {end}", "mm", "laser", 0.2, 1.2, 2.5, f"wheel_{end}", True))
        r.append(_reading("wheels", f"rim_radial_{end}", f"Rim out of round, {end}", "mm", "laser", 0.2, 1.0, 2.2, f"wheel_{end}", True))
        r.append(_reading("wheels", f"rim_wall_{end}", f"Rim wall thickness, {end}", "mm", "ultrasound", 1.8, 1.2, 0.9, f"wheel_{end}", True))
        r.append(_reading("wheels", f"rim_crack_{end}", f"Rim crack depth, {end}", "mm", "ultrasound", 0.0, 0.2, 0.5, f"wheel_{end}", True))
        r.append(_reading("wheels", f"spokes_broken_{end}", f"Broken spokes, {end}", "count", "camera", 0, 1, 2, f"wheel_{end}", True))
        r.append(_reading("tyres", f"tyre_tread_{end}", f"Tread depth, {end}", "mm", "laser", 2.5, 1.0, 0.5, f"tyre_{end}", True))
        r.append(_reading("tyres", f"tyre_sidewall_{end}", f"Sidewall cracks, {end}", "mm", "camera", 0.0, 1.0, 3.0, f"tyre_{end}", True))
        r.append(_reading("tyres", f"tyre_pressure_loss_{end}", f"Pressure lost per day, {end}", "bar", "pressure sensor", 0.05, 0.4, 1.0, f"tyre_{end}"))
        r.append(_reading("tyres", f"tyre_bead_{end}", f"Tyre seating error, {end}", "mm", "laser", 0.1, 0.8, 1.5, f"tyre_{end}", True))
        r.append(_reading("tyres", f"tyre_embedded_{end}", f"Glass or metal in the tread, {end}", "count", "camera", 0, 2, 5, f"tyre_{end}"))
        r.append(_reading("hubs", f"hub_play_{end}", f"Bearing play, {end} hub", "mm", "load robot", 0.03, 0.2, 0.5, f"hub_bearing_{end}", True))
        r.append(_reading("hubs", f"hub_noise_{end}", f"Bearing noise, {end} hub", "dB", "acoustic sensor", 20, 38, 52, f"hub_bearing_{end}"))
        r.append(_reading("hubs", f"hub_heat_{end}", f"Bearing warms up by, {end} hub", "°C", "thermal camera", 3, 14, 28, f"hub_bearing_{end}"))
        r.append(_reading("hubs", f"hub_grease_{end}", f"Grease left, {end} hub", "%", "spectrometer", 90, 40, 15, f"hub_bearing_{end}"))
        r.append(_reading("hubs", f"hub_axle_wear_{end}", f"Axle wear, {end}", "mm", "laser", 0.02, 0.15, 0.4, f"hub_bearing_{end}", True))

    # Bottom bracket and cranks
    r.append(_reading("bottom_bracket", "bb_play", "Bottom bracket play", "mm", "load robot", 0.03, 0.25, 0.6, "bottom_bracket", True))
    r.append(_reading("bottom_bracket", "bb_noise", "Bottom bracket noise", "dB", "acoustic sensor", 22, 40, 54, "bottom_bracket"))
    r.append(_reading("bottom_bracket", "bb_drag", "Drag when pedalling", "Nm", "torque robot", 0.1, 0.6, 1.2, "bottom_bracket"))
    r.append(_reading("bottom_bracket", "bb_heat", "Warms up by", "°C", "thermal camera", 3, 14, 28, "bottom_bracket"))
    for side in ("left", "right"):
        r.append(_reading("bottom_bracket", f"crank_crack_{side}", f"Crack depth, {side} crank", "mm", "ultrasound", 0.0, 0.2, 0.5, "crank", True))
        r.append(_reading("bottom_bracket", f"crank_bolt_{side}", f"Crank bolt torque lost, {side}", "%", "torque robot", 2, 20, 45, "crank", True))
        r.append(_reading("bottom_bracket", f"pedal_play_{side}", f"Pedal bearing play, {side}", "mm", "load robot", 0.05, 0.5, 1.2, "pedals"))
        r.append(_reading("bottom_bracket", f"pedal_thread_{side}", f"Pedal thread wear, {side}", "%", "camera", 2, 25, 55, "pedals", True))

    # Chain and gears
    r.append(_reading("drivetrain", "chain_stretch", "Chain stretch", "%", "laser", 0.1, 0.5, 0.75, "chain", True))
    r.append(_reading("drivetrain", "chain_stiff_links", "Stiff chain links", "count", "camera", 0, 2, 6, "chain"))
    r.append(_reading("drivetrain", "chain_corrosion", "Chain corrosion", "%", "multispectral camera", 2, 25, 55, "chain"))
    r.append(_reading("drivetrain", "cassette_wear", "Cassette tooth wear", "%", "laser", 5, 45, 75, "cassette"))
    r.append(_reading("drivetrain", "cassette_skip", "Gear skips under load", "per 100", "torque robot", 0, 2, 6, "cassette", True))
    r.append(_reading("drivetrain", "chainring_wear", "Chainring tooth wear", "%", "laser", 5, 45, 75, "chainring"))
    r.append(_reading("drivetrain", "chainring_bolts", "Chainring bolt torque lost", "%", "torque robot", 2, 20, 45, "chainring"))
    r.append(_reading("drivetrain", "hanger_alignment", "Derailleur hanger bent", "mm", "laser", 0.3, 3, 6, "rear_derailleur"))
    r.append(_reading("drivetrain", "jockey_wear", "Jockey wheel wear", "%", "camera", 5, 45, 75, "rear_derailleur"))
    r.append(_reading("drivetrain", "shift_accuracy", "Clean gear changes", "%", "shift robot", 99, 90, 75, "rear_derailleur"))
    r.append(_reading("drivetrain", "derailleur_spring", "Derailleur spring force", "%", "load robot", 98, 70, 45, "rear_derailleur"))
    r.append(_reading("drivetrain", "freehub_slip", "Freehub slip under load", "per 100", "torque robot", 0, 1, 3, "wheel_rear", True))

    # Brakes, front and rear. Pads are measured twice, by two different instruments.
    for end in ("front", "rear"):
        r.append(_reading("brakes", f"pad_{end}_laser", f"Brake pad left, {end} (laser)", "mm", "laser", 4.0, 1.5, 0.8, f"brake_pads_{end}", True))
        r.append(_reading("brakes", f"pad_{end}_camera", f"Brake pad left, {end} (camera)", "mm", "camera", 4.0, 1.5, 0.8, f"brake_pads_{end}", True))
        r.append(_reading("brakes", f"rotor_thickness_{end}", f"Rotor thickness, {end}", "mm", "laser", 2.0, 1.7, 1.5, f"brake_rotor_{end}", True))
        r.append(_reading("brakes", f"rotor_runout_{end}", f"Rotor wobble, {end}", "mm", "laser", 0.05, 0.3, 0.6, f"brake_rotor_{end}", True))
        r.append(_reading("brakes", f"rotor_crack_{end}", f"Rotor crack depth, {end}", "mm", "ultrasound", 0.0, 0.1, 0.3, f"brake_rotor_{end}", True))
        r.append(_reading("brakes", f"brake_force_{end}", f"Stopping force, {end}", "% of new", "brake robot", 98, 80, 65, f"brake_caliper_{end}", True))
        r.append(_reading("brakes", f"lever_travel_{end}", f"Lever travel before biting, {end}", "mm", "brake robot", 12, 28, 42, f"brake_caliper_{end}", True))
        r.append(_reading("brakes", f"caliper_stick_{end}", f"Caliper piston sticking, {end}", "%", "brake robot", 2, 25, 55, f"brake_caliper_{end}", True))
        r.append(_reading("brakes", f"fluid_leak_{end}", f"Brake fluid leak, {end}", "ml", "thermal camera", 0.0, 0.2, 0.8, f"brake_caliper_{end}", True))

    # Cables and controls
    for what, part in (("front brake", "cables"), ("rear brake", "cables"), ("front gear", "cables"), ("rear gear", "cables")):
        slug = what.replace(" ", "_")
        safety = "brake" in what
        r.append(_reading("controls", f"cable_fray_{slug}", f"Frayed strands, {what} cable", "count", "camera", 0, 2, 5, part, safety))
        r.append(_reading("controls", f"cable_drag_{slug}", f"Cable drag, {what}", "N", "load robot", 2, 9, 16, part))
    r.append(_reading("controls", "bar_clamp", "Handlebar clamp torque lost", "%", "torque robot", 2, 20, 45, "stem", True))
    r.append(_reading("controls", "stem_clamp", "Stem clamp torque lost", "%", "torque robot", 2, 20, 45, "stem", True))

    # Saddle, bars and lights
    r.append(_reading("contact", "bar_crack", "Handlebar crack depth", "mm", "ultrasound", 0.0, 0.1, 0.3, "handlebar", True))
    r.append(_reading("contact", "stem_crack", "Stem crack depth", "mm", "ultrasound", 0.0, 0.1, 0.3, "stem", True))
    r.append(_reading("contact", "seatpost_crack", "Seatpost crack depth", "mm", "ultrasound", 0.0, 0.2, 0.5, "seatpost", True))
    r.append(_reading("contact", "seatpost_slip", "Seatpost slips under load", "mm", "load robot", 0, 3, 8, "seatpost"))
    r.append(_reading("contact", "saddle_rail", "Saddle rail bent", "mm", "laser", 0.2, 2, 5, "saddle"))
    r.append(_reading("contact", "grip_wear", "Grip wear", "%", "camera", 5, 50, 80, "grips"))
    r.append(_reading("contact", "light_front", "Front light output", "% of new", "light meter", 98, 70, 40, "lights", True))
    r.append(_reading("contact", "light_rear", "Rear light output", "% of new", "light meter", 98, 70, 40, "lights", True))
    r.append(_reading("contact", "reflectors", "Missing reflectors", "count", "camera", 0, 1, 3, "lights"))
    r.append(_reading("contact", "kickstand_play", "Kickstand play", "mm", "load robot", 1, 6, 12, "kickstand"))
    return r


def _electric_catalogue() -> list[dict]:
    r = [
        _reading("battery", "battery_health", "Battery capacity left", "% of new", "charge robot", 97, 75, 60, "battery", True),
        _reading("battery", "battery_resistance", "Internal resistance", "mΩ", "charge robot", 90, 160, 240, "battery", True),
        _reading("battery", "battery_heat", "Warms up on charge by", "°C", "thermal camera", 6, 20, 32, "battery", True),
        _reading("battery", "battery_case_crack", "Battery case crack", "mm", "camera", 0.0, 0.5, 2.0, "battery", True),
        _reading("battery", "battery_swelling", "Battery case swelling", "mm", "laser", 0.0, 0.6, 1.5, "battery", True),
        _reading("battery", "battery_connector", "Connector corrosion", "%", "multispectral camera", 2, 25, 55, "battery"),
        _reading("battery", "bms_faults", "Battery computer faults, last 30 days", "count", "diagnostic port", 0, 2, 6, "battery", True),
    ]
    for cell in range(1, 11):
        r.append(_reading("battery", f"cell_gap_{cell}", f"Cell group {cell}: gap to the average", "mV", "charge robot",
                          8, 60, 130, "battery", True))
    r += [
        _reading("motor", "motor_torque", "Motor torque", "% of new", "torque robot", 98, 80, 60, "motor"),
        _reading("motor", "motor_noise", "Motor bearing noise", "dB", "acoustic sensor", 26, 44, 58, "motor"),
        _reading("motor", "motor_heat", "Motor warms up by", "°C", "thermal camera", 10, 32, 50, "motor"),
        _reading("motor", "motor_mount", "Motor mount torque lost", "%", "torque robot", 2, 20, 45, "motor", True),
        _reading("motor", "torque_sensor", "Torque sensor error", "%", "diagnostic port", 1, 8, 18, "controller"),
        _reading("motor", "speed_sensor", "Speed sensor error", "%", "diagnostic port", 1, 8, 18, "controller", True),
        _reading("motor", "controller_faults", "Controller faults, last 30 days", "count", "diagnostic port", 0, 2, 6, "controller"),
        _reading("motor", "wiring_insulation", "Wiring insulation damage", "%", "multispectral camera", 1, 15, 35, "wiring", True),
        _reading("motor", "wiring_connectors", "Loose connectors", "count", "camera", 0, 1, 3, "wiring"),
        _reading("motor", "display_faults", "Display faults", "count", "diagnostic port", 0, 2, 6, "controller"),
    ]
    return r


CATALOGUE = _catalogue()
ELECTRIC_CATALOGUE = _electric_catalogue()
READING_NAMES = {d["key"]: d["name"] for d in CATALOGUE + ELECTRIC_CATALOGUE}


def catalogue_for(bike: Bike) -> list[dict]:
    return CATALOGUE + ELECTRIC_CATALOGUE if bike.category in ELECTRIC else CATALOGUE


def _past(value: float, reading: dict, limit: str) -> bool:
    """Is `value` at or beyond the limit? Works for both directions."""
    low_is_bad = reading["unfit"] < reading["nominal"]
    return value <= reading[limit] if low_is_bad else value >= reading[limit]


def measure(bike: Bike, hours: float, faults: dict, scan_no: int = 0) -> list[dict]:
    """
    One scan's values. Normal wear grows with hours and always stays inside the
    limits; each bike wears each part at its own rate, so scans are comparable.
    `faults` is {reading key: {"value": number}}.
    """
    wear = min(hours / HOURS_TO_WEAR_OUT, MOST_NORMAL_WEAR)
    noise = random.Random(f"{bike.code}:{scan_no}:{hours:.1f}")
    readings = []
    for d in catalogue_for(bike):
        rate = random.Random(f"{bike.code}:{d['key']}").uniform(.4, 1)
        span = d["watch"] - d["nominal"]
        value = d["nominal"] + span * wear * rate + span * noise.uniform(-.015, .015)
        low, high = sorted((d["nominal"] - abs(span) * .05, d["nominal"] + span * .85))
        if d["unit"] == "count":
            value = 0
        value = round(max(low, min(high, value)), 3)
        if d["key"] in faults:
            value = faults[d["key"]]["value"]
        readings.append({**d, "value": value})
    return readings


def grade(readings: list[dict], previous: Optional[list[dict]] = None) -> list[dict]:
    """THE SAFETY GATE: give each reading its status from the fixed limits, nothing else."""
    before = {r["key"]: r["value"] for r in previous or []}
    for r in readings:
        r["status"] = OK
        if _past(r["value"], r, "unfit"):
            r["status"] = UNFIT
        elif _past(r["value"], r, "watch"):
            r["status"] = WATCH
        elif r["key"] in before:
            span = abs(r["watch"] - r["nominal"])
            if span and (r["value"] - before[r["key"]]) * (1 if r["watch"] > r["nominal"] else -1) >= TREND_SHARE * span:
                r["status"] = TREND
    return readings


def verdict(readings: list[dict]) -> str:
    """fit | watch | unfit for a whole bike. Only a new scan can change it."""
    statuses = {r["status"] for r in readings}
    if UNFIT in statuses:
        return UNFIT
    return WATCH if statuses & {WATCH, TREND} else FIT


def findings(readings: list[dict]) -> list[dict]:
    return [r for r in readings if r["status"] != OK]


def hours_used(db: Session, bike_id: int) -> float:
    """Hours the bike was out, from its returned rentals (at most 8 riding hours count per day)."""
    rentals = db.exec(select(Rental).where(Rental.bike_id == bike_id, Rental.status == RentalStatus.returned)).all()
    total = 0.0
    for r in rentals:
        if r.picked_up_at and r.returned_at:
            hours = (r.returned_at - r.picked_up_at).total_seconds() / 3600
            total += min(hours, 8 * (hours // 24 + 1))
    return round(total, 1)


def done_scans(db: Session, bike_id: int) -> list[WorkshopScan]:
    """The bike's finished scans, newest first."""
    return db.exec(select(WorkshopScan).where(WorkshopScan.bike_id == bike_id, WorkshopScan.status == "done")
                   .order_by(WorkshopScan.scanned_at.desc(), WorkshopScan.id.desc())).all()


def previous_scan(db: Session, scan: WorkshopScan) -> Optional[WorkshopScan]:
    earlier = [s for s in done_scans(db, scan.bike_id) if s.id != scan.id and s.id < scan.id]
    return earlier[0] if earlier else None


def record_scan(db: Session, bike: Bike, faults: dict, rental_id: Optional[int] = None,
                scan: Optional[WorkshopScan] = None) -> WorkshopScan:
    """Measure the bike and store the scan. No AI, no job. Doesn't commit."""
    earlier = done_scans(db, bike.id)
    readings = measure(bike, hours_used(db, bike.id), faults, len(earlier))
    grade(readings, earlier[0].readings if earlier else None)
    scan = scan or WorkshopScan(bike_id=bike.id, rental_id=rental_id)
    scan.status, scan.scanned_at, scan.readings = "done", utcnow(), readings
    scan.verdict, scan.faults = verdict(readings), faults
    db.add(scan)
    db.flush()
    return scan


def get_scan(db: Session, scan_id: int) -> WorkshopScan:
    scan = db.get(WorkshopScan, scan_id)
    if not scan:
        raise NotFound(f"There is no scan with id {scan_id}.")
    return scan


def overview(scan: WorkshopScan, previous: Optional[WorkshopScan] = None) -> list[dict]:
    """
    One line per group: the agent starts here, so the whole scan never goes into
    a prompt (SPEC §14.10). `moved_most` shows the reading that moved furthest
    towards its limit since the last scan, so slow wear is visible too.
    """
    before = {r["key"]: r["value"] for r in previous.readings} if previous else {}
    rank = {OK: 0, TREND: 1, WATCH: 2, UNFIT: 3}
    groups = {}
    for r in scan.readings:
        groups.setdefault(r["group"], []).append(r)
    result = []
    for group, readings in groups.items():
        worst = max(readings, key=lambda r: (rank[r["status"]], abs(r["value"] - r["nominal"]) / (abs(r["watch"] - r["nominal"]) or 1)))
        row = {"group": group, "label": GROUP_LABELS[group], "readings": len(readings), "status": worst["status"],
               "problems": sum(r["status"] != OK for r in readings),
               "worst": {k: worst[k] for k in ("key", "name", "value", "unit", "watch", "unfit")}}
        moved = [(abs(r["value"] - before[r["key"]]) / (abs(r["watch"] - r["nominal"]) or 1), r) for r in readings if r["key"] in before]
        if moved:
            share, r = max(moved, key=lambda m: m[0])
            row["moved_most"] = {"key": r["key"], "name": r["name"], "from": before[r["key"]], "to": r["value"],
                                 "share_of_way_to_watch_limit": round(share, 2)}
        result.append(row)
    return result


def waiting_bikes(db: Session) -> list[WorkshopScan]:
    """Returned bikes waiting for the machine (SPEC §14.2): scans aren't automatic."""
    return db.exec(select(WorkshopScan).where(WorkshopScan.status == "waiting").order_by(WorkshopScan.id)).all()


def rental_bikes(db: Session) -> list[Bike]:
    return db.exec(select(Bike).where(Bike.purpose == Purpose.rental)).all()
