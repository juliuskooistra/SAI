"""
The Workshop (SPEC §14): cases, the numbers behind the options, and staff actions.

This file is everything EXCEPT the AI. It moves a case through its stages,
works out what an option costs and when the bike is ready, checks what the agent
hands in, and carries out what staff decide. `workshop_agent.py` runs the model.

The idea in one line: the agent reasons and argues, this code checks the facts
and the safety limits, and the human decides.
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from ..config import (
    AS_IS_DISCOUNT, HOLIDAYS, MECHANIC_CHF_PER_HOUR, MECHANIC_HOURS_PER_DAY, OPENING_HOURS,
    SALE_TARGET_MARGIN, SCRAP_SHARE, WORKSHOP_MAX_STAFF_MESSAGES,
)
from ..database import start_write_transaction
from ..jobqueue import queue
from ..models.models import (
    Bike, BikeCreateRequest, BikeFinance, BikeStatus, BikeUpdateRequest, Condition, CustomerAction, PartOffer,
    Purpose, Rental, RentalStatus, Supplier, User, WorkshopCase, WorkshopEvent, WorkshopScan,
)
from ..timeutils import to_local, utcnow
from . import scan_service
from .errors import Conflict, NotFound, RuleViolation
from .inventory_service import InventoryService
from .notification_service import NotificationService
from .pricing_service import money
from .rental_service import OPEN_STATUSES, RentalService

# The stages of a case (SPEC §14.1)
OPEN, ANALYSING, CHOOSING, DISCUSSING, PLANNING, PLAN_REVIEW = \
    "open", "analysing", "choosing", "discussing", "planning", "plan_review"
APPROVED, IN_REPAIR, RESCAN, CLOSED = "approved", "in_repair", "rescan", "closed"
AGENT_STAGES = {ANALYSING, DISCUSSING, PLANNING, PLAN_REVIEW}    # where the model may be working
ACTIVE = {OPEN, ANALYSING, CHOOSING, DISCUSSING, PLANNING, PLAN_REVIEW, APPROVED, IN_REPAIR, RESCAN}

# What an option can be
REPAIR, REPAIR_AND_SELL, SELL_AS_IS, KEEP_WATCH, SCRAP = \
    "repair", "repair_and_sell", "sell_as_is", "keep_watch", "scrap"
OPTION_KINDS = (REPAIR, REPAIR_AND_SELL, SELL_AS_IS, KEEP_WATCH, SCRAP)
NEEDS_PARTS = (REPAIR, REPAIR_AND_SELL)
LEAVES_THE_FLEET = (REPAIR_AND_SELL, SELL_AS_IS, SCRAP)
NOT_WITH_UNFIT = (KEEP_WATCH, SELL_AS_IS)     # these leave an unfit bike as it is (SPEC §14.3)

VERDICT_WORDS, OPTION_WORDS, SUMMARY_WORDS = 25, 30, 60
TIMELINE_DAYS = 30


# ---------------------------------------------------------------- calendar

def is_open(day: date) -> bool:
    return day.weekday() in OPENING_HOURS and day not in HOLIDAYS


def next_open(day: date) -> date:
    while not is_open(day):
        day += timedelta(days=1)
    return day


def today() -> date:
    return to_local(utcnow()).date()


# ---------------------------------------------------------------- reading

def get_case(db: Session, case_id: int) -> WorkshopCase:
    case = db.get(WorkshopCase, case_id)
    if not case:
        raise NotFound(f"There is no workshop case with id {case_id}.")
    return case


def get_bike(db: Session, bike_id: int) -> Bike:
    bike = db.get(Bike, bike_id)
    if not bike:
        raise NotFound(f"There is no bike with id {bike_id}.")
    return bike


def open_case_for(db: Session, bike_id: int) -> Optional[WorkshopCase]:
    return db.exec(select(WorkshopCase).where(WorkshopCase.bike_id == bike_id, WorkshopCase.stage != CLOSED)).first()


def case_scan(db: Session, case: WorkshopCase) -> WorkshopScan:
    return db.get(WorkshopScan, case.scan_id)


def list_cases(db: Session, active_only: bool = True) -> list[WorkshopCase]:
    """Most urgent first: unsafe bikes, then the nearest pick-up."""
    query = select(WorkshopCase)
    if active_only:
        query = query.where(WorkshopCase.stage != CLOSED)

    def urgency(case: WorkshopCase) -> tuple:
        bookings = upcoming_bookings(db, case.bike_id)
        return (case_scan(db, case).verdict != scan_service.UNFIT,
                to_local(bookings[0].start_at).isoformat() if bookings else "9999", case.id)
    return sorted(db.exec(query).all(), key=urgency)


def events_of(db: Session, case_id: int) -> list[WorkshopEvent]:
    return db.exec(select(WorkshopEvent).where(WorkshopEvent.case_id == case_id).order_by(WorkshopEvent.id)).all()


def log(db: Session, case: WorkshopCase, author: str, kind: str, content: str = "", data: Optional[dict] = None,
        reasoning: Optional[str] = None, tokens: int = 0) -> WorkshopEvent:
    """Write down what happened. The page's "How the agent worked" is this list. Doesn't commit."""
    event = WorkshopEvent(case_id=case.id, stage=case.stage, author=author, kind=kind, content=content,
                          data=data, reasoning=reasoning, tokens=tokens)
    db.add(event)
    return event


def notice_lost_agent(db: Session, case: WorkshopCase) -> None:
    """
    The app restarted, or a job died: no job is left for a case that says the agent
    is working. Say so, so the page offers Retry and staff can carry on. Commits.
    """
    if case.agent_state not in ("working", "waiting"):
        return
    jobs = queue.list_jobs(db, kind="workshop_step", limit=50)
    if any(j.status in (queue.QUEUED, queue.RUNNING) and j.payload.get("case_id") == case.id for j in jobs):
        return
    case.agent_state, case.agent_note = "failed", "The agent stopped. Press Retry, or write to it again."
    db.add(case)
    db.commit()


def start_agent(db: Session, case: WorkshopCase) -> None:
    """Hand the case to the agent: one `workshop_step` job, one model round. Doesn't commit."""
    case.step_no += 1
    case.agent_state, case.agent_note = "working", None
    case.updated_at = utcnow()
    db.add(case)
    queue.enqueue(db, "workshop_step", {"case_id": case.id, "step_no": case.step_no, "retries": 0}, max_attempts=1)


# ---------------------------------------------------------------- scanning

def run_scan(db: Session, bike_id: int) -> tuple[WorkshopScan, Optional[WorkshopCase]]:
    """Put a bike through the machine: code only, no AI and no job (SPEC §14.2). Opens or feeds a case."""
    start_write_transaction(db)
    try:
        bike = get_bike(db, bike_id)
        if bike.purpose != Purpose.rental:
            raise RuleViolation("Only rental bikes go through the diagnostic machine.")
        case = open_case_for(db, bike_id)
        waiting = db.exec(select(WorkshopScan).where(WorkshopScan.bike_id == bike_id,
                                                     WorkshopScan.status == "waiting")).first()
        if case and case.stage != RESCAN and not waiting:
            raise Conflict("This bike has a scan, and the scan is trusted. It goes through the machine again "
                           "only after its repair.")
        faults = waiting.faults if waiting else {}      # after a repair the bike is as good as new
        rental_id = waiting.rental_id if waiting else None
        scan = scan_service.record_scan(db, bike, faults, rental_id, waiting)
        case = _after_scan(db, bike, scan, case)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(scan)
    return scan, case


def _after_scan(db: Session, bike: Bike, scan: WorkshopScan, case: Optional[WorkshopCase]) -> Optional[WorkshopCase]:
    """A finding opens a case; no finding closes as fit, without any AI call (SPEC §14.1)."""
    if case is None:
        case = WorkshopCase(bike_id=bike.id, scan_id=scan.id,
                            stage=OPEN if scan.verdict != scan_service.FIT else CLOSED,
                            outcome=None if scan.verdict != scan_service.FIT else "no_finding")
        db.add(case)
        db.flush()
        log(db, case, "code", "note", f"Scan {scan.id}: {scan.verdict}.")
        return case
    case.scan_id = scan.id
    case.updated_at = utcnow()
    log(db, case, "code", "note", f"New scan {scan.id}: {scan.verdict}.")
    db.add(case)
    return case


# ---------------------------------------------------------------- the numbers (code, never the model)

def offer_total(db: Session, offer: PartOffer) -> Decimal:
    supplier = db.get(Supplier, offer.supplier_id)
    return money(offer.price_chf + supplier.shipping_chf)


def describe_offer(db: Session, offer: PartOffer) -> dict:
    supplier = db.get(Supplier, offer.supplier_id)
    return {"offer_id": offer.id, "part": offer.part, "label": offer.label, "supplier": supplier.name,
            "country": supplier.country, "quality": offer.quality, "price_chf": str(offer.price_chf),
            "shipping_chf": str(supplier.shipping_chf), "total_chf": str(offer_total(db, offer)),
            "delivery_days": offer.delivery_days, "repair_hours": str(offer.repair_hours),
            "safety_part": offer.safety_part}


def offers_for(db: Session, bike: Bike, part: str) -> list[PartOffer]:
    offers = db.exec(select(PartOffer).where(PartOffer.part == part)).all()
    return [o for o in offers if bike.category.value in o.fits]


def mechanic_load(db: Session, exclude_case_id: Optional[int] = None) -> dict[date, Decimal]:
    """Booked mechanic hours per day, from cases with an approved plan."""
    load: dict[date, Decimal] = {}
    cases = db.exec(select(WorkshopCase).where(WorkshopCase.stage.in_([APPROVED, IN_REPAIR]))).all()
    for case in cases:
        if case.id == exclude_case_id or not case.repair_day:
            continue
        day, left = next_open(max(case.repair_day, today())), Decimal(case.repair_hours)
        while left > 0:
            free = max(MECHANIC_HOURS_PER_DAY - load.get(day, Decimal("0")), Decimal("0"))
            used = min(free, left)
            load[day] = load.get(day, Decimal("0")) + used
            left -= used
            day = next_open(day + timedelta(days=1))
    return load


def estimate_ready(db: Session, delivery_days: int, hours: Decimal, exclude_case_id: Optional[int] = None) -> dict:
    """
    When is the bike ready? Parts first, then the mechanic's free hours, on open
    days. There is one mechanic, so a busy week pushes the date (SPEC §14.12, D7).
    """
    arrives = next_open(today() + timedelta(days=int(delivery_days)))
    if hours <= 0:
        return {"parts_arrive": arrives, "repair_starts": arrives, "ready": arrives, "days_waiting_for_mechanic": 0}
    load = mechanic_load(db, exclude_case_id)
    day, left, starts = arrives, Decimal(hours), None
    while True:
        free = max(MECHANIC_HOURS_PER_DAY - load.get(day, Decimal("0")), Decimal("0"))
        if free > 0:
            starts = starts or day
            left -= free
            if left <= 0:
                return {"parts_arrive": arrives, "repair_starts": starts, "ready": day,
                        "days_waiting_for_mechanic": (starts - arrives).days}
        day = next_open(day + timedelta(days=1))


def upcoming_bookings(db: Session, bike_id: int) -> list[Rental]:
    rentals = db.exec(select(Rental).where(Rental.bike_id == bike_id, Rental.status == RentalStatus.booked)
                      .order_by(Rental.start_at)).all()
    return [r for r in rentals if to_local(r.start_at).date() >= today()]


def affected_bookings(db: Session, bike_id: int, ready: Optional[date], leaves_fleet: bool = False) -> list[Rental]:
    """Bookings that start before the bike is back, or all of them if it never comes back."""
    if leaves_fleet:
        return upcoming_bookings(db, bike_id)
    if ready is None:
        return []
    return [r for r in upcoming_bookings(db, bike_id) if to_local(r.start_at).date() <= ready]


def income_last_year(db: Session, bike_id: int) -> Decimal:
    since = utcnow() - timedelta(days=365)
    rentals = db.exec(select(Rental).where(Rental.bike_id == bike_id, Rental.status == RentalStatus.returned)).all()
    return money(sum((r.final_price_chf or Decimal("0") for r in rentals
                      if r.start_at.replace(tzinfo=since.tzinfo) >= since), Decimal("0")))


def sale_price(book_value: Decimal, repair_cost: Decimal, market_value: Decimal) -> dict:
    """List price at the target margin ON THE PRICE, with the market value as a ceiling (SPEC §14.8)."""
    cost = Decimal(book_value) + Decimal(repair_cost)
    wanted = money(cost / (1 - SALE_TARGET_MARGIN))
    price = min(wanted, money(market_value))
    margin = (price - cost) / price if price else Decimal("0")
    return {"list_price_chf": str(price), "margin_percent": str((margin * 100).quantize(Decimal("0.1"))),
            "below_target": bool(margin < SALE_TARGET_MARGIN)}


def economics(db: Session, bike_id: int, repair_cost: Decimal) -> dict:
    """Keep, repair and sell, sell as is, or scrap: the sums, by code (SPEC §14.8)."""
    finance = db.get(BikeFinance, bike_id)
    if not finance:
        raise NotFound(f"There are no financial data for bike {bike_id}.")
    repair_cost = money(repair_cost)
    income = income_last_year(db, bike_id)
    sell = sale_price(finance.book_value_chf, repair_cost, finance.market_value_chf)
    return {
        "book_value_chf": str(finance.book_value_chf), "market_value_chf": str(finance.market_value_chf),
        "repair_cost_chf": str(repair_cost),
        "keep": {"rental_income_last_12_months_chf": str(income), "income_minus_repair_chf": str(money(income - repair_cost))},
        "repair_and_sell": {**sell, "net_after_repair_chf": str(money(Decimal(sell["list_price_chf"]) - repair_cost))},
        "sell_as_is": {"price_chf": str(money(finance.market_value_chf * (1 - AS_IS_DISCOUNT)))},
        "scrap": {"parts_value_chf": str(money(finance.market_value_chf * SCRAP_SHARE))},
    }


def priced_option(db: Session, case: WorkshopCase, kind: str, offer_ids: list) -> dict:
    """What an option means in francs and days. The agent picks; this computes (SPEC §14.5)."""
    bike = get_bike(db, case.bike_id)
    offers, repairs = [], []
    for offer_id in offer_ids:
        offer = db.get(PartOffer, int(offer_id))
        if not offer:
            raise RuleViolation(f"There is no part offer {offer_id}.")
        if bike.category.value not in offer.fits:
            raise RuleViolation(f"Offer {offer_id} ({offer.label}) doesn't fit a {bike.category.value} bike.")
        if offer.safety_part and offer.quality == "used":
            raise RuleViolation(f"Offer {offer_id} is a used {offer.label}. A used part never goes on a safety part.")
        offers.append(offer)
        repairs.append(describe_offer(db, offer))
    hours = sum((o.repair_hours for o in offers), Decimal("0"))
    parts_chf = sum((offer_total(db, o) for o in offers), Decimal("0"))
    labour_chf = money(hours * MECHANIC_CHF_PER_HOUR)
    delivery = max((o.delivery_days for o in offers), default=0)
    dates = estimate_ready(db, delivery, hours, case.id)
    ready: Optional[date] = dates["ready"]
    if kind == KEEP_WATCH:
        ready = None        # it never left service
    leaves = kind in LEAVES_THE_FLEET
    rentable_again = None if leaves else ready
    return {"parts": repairs, "repair_hours": str(hours), "parts_chf": str(money(parts_chf)),
            "labour_chf": str(labour_chf), "cost_chf": str(money(parts_chf + labour_chf)),
            "parts_arrive": dates["parts_arrive"].isoformat(), "repair_starts": dates["repair_starts"].isoformat(),
            "days_waiting_for_mechanic": dates["days_waiting_for_mechanic"],
            "work_done": ready.isoformat() if ready else None,
            "ready_date": rentable_again.isoformat() if rentable_again else None,
            "bookings_affected": [r.id for r in affected_bookings(db, case.bike_id, ready, leaves)]}


# The scan is trusted (SPEC §14.3). Words that doubt it, or ask for another one, are refused. A
# reading can be called "Torque sensor error": that is a measurement, so it doesn't count.
DOUBT = re.compile(r"\bre-?scan|scan(ning)? (it |the \w+ )?again|another scan|new scan|(?<!torque )(?<!speed )sensor (fault|error|glitch|problem)"
                   r"|faulty (reading|sensor|scan)|false alarm|misread|wrong reading|measurement error"
                   r"|re-?(check|test|measure)|(may|might|could) (be|have been) (a |an )?(error|mistake|wrong)", re.I)
TRUST_THE_SCAN = ("The machine's readings are always right. Don't question them and don't suggest scanning again: "
                  "the bike goes through the machine again only after its repair. Rewrite this.")


def doubts_the_scan(*texts: str) -> bool:
    return any(DOUBT.search(str(text)) for text in texts)


def _words(text: str) -> int:
    return len(str(text).split())


def _score(values: list[float], lower_is_better: bool = True) -> list[int]:
    """Turn numbers into 1-5 for the bars on the option cards."""
    low, high = min(values), max(values)
    if high == low:
        return [5] * len(values)
    return [round(1 + 4 * ((high - v) if lower_is_better else (v - low)) / (high - low)) for v in values]


def _safety_score(kind: str, offers: list) -> int:
    """How safe the path is for riders. Bikes that leave the fleet or stay out can't hurt a renter."""
    if kind == SCRAP:
        return 5
    if kind == KEEP_WATCH:
        return 3
    if kind == SELL_AS_IS:
        return 2
    return 5 if all(o["quality"] == "new_oem" for o in offers) else 4


def submit_brief(db: Session, case: WorkshopCase, brief: dict) -> dict:
    """
    Check the agent's brief, add our numbers, and show it to staff. A problem comes
    back as {"error": ...}, which the agent reads and fixes. This is where the
    safety gate meets the agent's options (SPEC §14.3).
    """
    scan = case_scan(db, case)
    unfit = [r for r in scan.readings if r["status"] == scan_service.UNFIT]
    options = brief.get("options") or []
    if not 2 <= len(options) <= 4:
        return {"error": "Give 2 to 4 options."}
    sentence, summary = brief.get("verdict_sentence", ""), brief.get("what_is_wrong", "")
    if not sentence or _words(sentence) > VERDICT_WORDS:
        return {"error": f"verdict_sentence needs 1 to {VERDICT_WORDS} words."}
    if not summary or _words(summary) > SUMMARY_WORDS:
        return {"error": f"what_is_wrong needs 1 to {SUMMARY_WORDS} words."}
    if doubts_the_scan(sentence, summary, brief.get("recommended_why", ""),
                       *[f"{o.get('title', '')} {o.get('what_we_do', '')}" for o in options]):
        return {"error": TRUST_THE_SCAN}

    cards = []
    for n, option in enumerate(options):
        kind, key = option.get("kind"), "ABCD"[n]
        if kind not in OPTION_KINDS:
            return {"error": f"Option {key}: kind must be one of {', '.join(OPTION_KINDS)}."}
        if _words(option.get("what_we_do", "")) > OPTION_WORDS or not option.get("what_we_do"):
            return {"error": f"Option {key}: what_we_do needs 1 to {OPTION_WORDS} words."}
        if unfit and kind in NOT_WITH_UNFIT:
            return {"error": f"Option {key} leaves an unfit bike as it is. That isn't allowed: "
                             f"{', '.join(r['name'] for r in unfit)}."}
        offer_ids = option.get("offer_ids") or []
        if kind in NEEDS_PARTS and not offer_ids and unfit:
            return {"error": f"Option {key} is a repair but names no part offers."}
        try:
            priced = priced_option(db, case, kind, offer_ids)
        except (RuleViolation, TypeError, ValueError) as e:
            return {"error": f"Option {key}: {getattr(e, 'message', e)}"}
        if kind in NEEDS_PARTS:
            fixed = {p["part"] for p in priced["parts"]}
            missing = sorted({r["part"] for r in unfit} - fixed)
            if missing:
                return {"error": f"Option {key} doesn't fix every unfit reading. Still missing: {', '.join(missing)}."}
        cards.append({"key": key, "kind": kind, "title": str(option.get("title", ""))[:60],
                      "what_we_do": option["what_we_do"], **priced})

    recommended = brief.get("recommended")
    if recommended not in [c["key"] for c in cards]:
        return {"error": "recommended must be the key of one option: A, B, C or D."}

    costs = _score([float(c["cost_chf"]) for c in cards])
    days = _score([(date.fromisoformat(c["work_done"]) - today()).days if c["work_done"] else 0 for c in cards])
    for card, cost, speed in zip(cards, costs, days):
        card["scores"] = {"cost": cost, "speed": speed, "safety": _safety_score(card["kind"], card["parts"])}

    bike = get_bike(db, case.bike_id)
    horizon = today() + timedelta(days=TIMELINE_DAYS)
    case.brief = {
        "verdict": scan.verdict, "verdict_sentence": sentence, "what_is_wrong": summary,
        "groups": [{"group": g["group"], "label": g["label"], "status": g["status"]}
                   for g in scan_service.overview(scan)],
        "bookings": [{"rental_id": r.id, "start_at": to_local(r.start_at).isoformat(), "end_at": to_local(r.end_at).isoformat()}
                     for r in upcoming_bookings(db, bike.id) if to_local(r.start_at).date() <= horizon],
        "today": today().isoformat(), "timeline_end": horizon.isoformat(),
        "options": cards, "recommended": recommended, "recommended_why": str(brief.get("recommended_why", ""))[:300],
    }
    case.stage, case.agent_state = CHOOSING, "idle"
    case.updated_at = utcnow()
    db.add(case)
    log(db, case, "code", "note", "The brief passed the checks.")
    return {"ok": True, "options": [c["key"] for c in cards]}


def chosen_card(case: WorkshopCase) -> dict:
    return next(c for c in case.brief["options"] if c["key"] == case.chosen_option)


def submit_plan(db: Session, case: WorkshopCase, plan: dict) -> dict:
    """Check the agent's plan and add our numbers. Every affected booking needs an action (SPEC §14.6)."""
    card = chosen_card(case)
    priced = priced_option(db, case, card["kind"], [p["offer_id"] for p in card["parts"]])
    actions, seen = [], set()
    for a in plan.get("booking_actions") or []:
        kind = a.get("action")
        if kind not in ("email", "call", "move", "cancel"):
            return {"error": "Each booking action must be email, call, move or cancel."}
        rental = db.get(Rental, int(a.get("rental_id", 0)))
        if not rental or rental.bike_id != case.bike_id:
            return {"error": f"Rental {a.get('rental_id')} isn't a booking of this bike."}
        seen.add(rental.id)
        actions.append({"rental_id": rental.id, "action": kind, "why": str(a.get("why", ""))[:200],
                        "email_draft": str(a.get("email_draft", ""))[:1500]})
    missing = sorted(set(priced["bookings_affected"]) - seen)
    if missing:
        return {"error": f"These bookings are affected and have no action yet: {missing}."}
    if not plan.get("steps") or not plan.get("summary"):
        return {"error": "A plan needs a summary and steps."}
    sale = None
    if card["kind"] in (REPAIR_AND_SELL, SELL_AS_IS):       # the price staff will confirm (SPEC §14.8)
        sums = economics(db, case.bike_id, Decimal(priced["cost_chf"]))
        sale = sums["repair_and_sell"] if card["kind"] == REPAIR_AND_SELL else {"list_price_chf": sums["sell_as_is"]["price_chf"]}
    case.plan_version += 1
    case.plan = {"version": case.plan_version, "sale": sale, "summary": str(plan["summary"])[:500],
                 "steps": [str(s)[:200] for s in plan["steps"]][:12],
                 "fallback": str(plan.get("fallback", ""))[:300], "option": card["key"], "kind": card["kind"],
                 "booking_actions": actions, **priced}
    case.stage, case.agent_state = PLAN_REVIEW, "idle"
    case.updated_at = utcnow()
    db.add(case)
    log(db, case, "agent", "plan", case.plan["summary"], data=case.plan)
    return {"ok": True, "plan_version": case.plan_version}


# ---------------------------------------------------------------- staff decisions

def _in_stage(case: WorkshopCase, *stages: str) -> None:
    if case.stage not in stages:
        raise Conflict(f"This case is at stage '{case.stage}'; that can't be done now.")


def _idle(case: WorkshopCase) -> None:
    if case.agent_state in ("working", "waiting"):
        raise Conflict("The agent is still working on this case. Please wait for its answer.")


def _transaction(db: Session, case_id: int) -> WorkshopCase:
    start_write_transaction(db)
    return get_case(db, case_id)


def _commit(db: Session, case: WorkshopCase) -> WorkshopCase:
    case.updated_at = utcnow()
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _guarded(fn):
    """Run a staff action in one write transaction, and roll back if it fails."""
    def wrapper(db: Session, *args, **kwargs):
        try:
            return fn(db, *args, **kwargs)
        except Exception:
            db.rollback()
            raise
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


@_guarded
def analyse(db: Session, case_id: int) -> WorkshopCase:
    """Staff press Analyse: only now does the AI start (SPEC §14.2)."""
    case = _transaction(db, case_id)
    _in_stage(case, OPEN)
    case.stage = ANALYSING
    start_agent(db, case)
    return _commit(db, case)


@_guarded
def choose(db: Session, case_id: int, option: str) -> WorkshopCase:
    """Staff pick an option, or change it in the discussion. The agent must answer."""
    case = _transaction(db, case_id)
    _in_stage(case, CHOOSING, DISCUSSING)    # while the agent works too: this replaces what it was doing
    if option not in [c["key"] for c in case.brief["options"]]:
        raise RuleViolation(f"There is no option {option}.")
    case.chosen_option, case.stage, case.agent_agreed = option, DISCUSSING, None
    log(db, case, "staff", "choice", f"Option {option}", data={"option": option})
    start_agent(db, case)
    return _commit(db, case)


@_guarded
def say(db: Session, case_id: int, text: str) -> WorkshopCase:
    """A staff message in a discussion. It is data for the agent, never an instruction to it (SPEC §14.5)."""
    case = _transaction(db, case_id)
    _in_stage(case, DISCUSSING, PLAN_REVIEW)    # staff can always write: this replaces what the agent was doing
    written = [e for e in events_of(db, case.id) if e.stage == case.stage and e.author == "staff" and e.kind == "message"]
    if len(written) >= WORKSHOP_MAX_STAFF_MESSAGES:
        raise Conflict(f"This discussion has reached {WORKSHOP_MAX_STAFF_MESSAGES} messages. Please decide now.")
    log(db, case, "staff", "message", text)
    start_agent(db, case)
    return _commit(db, case)


@_guarded
def agree(db: Session, case_id: int) -> WorkshopCase:
    """
    Agreed, write the plan. Only after the agent has answered: the human has the
    final word, but must engage. If the agent disagreed, that stays on record.
    """
    case = _transaction(db, case_id)
    _in_stage(case, DISCUSSING)
    _idle(case)             # if the agent failed, the human can still decide: they have the final word
    if case.agent_agreed is None:
        case.agent_agreed = case.chosen_option == case.brief["recommended"]
    case.stage = PLANNING
    log(db, case, "staff", "decision", f"Agreed on option {case.chosen_option}.",
        data={"option": case.chosen_option, "agent_agreed": case.agent_agreed})
    start_agent(db, case)
    return _commit(db, case)


@_guarded
def retry(db: Session, case_id: int) -> WorkshopCase:
    """The model failed, or a job was lost: hand the case back to the agent."""
    case = _transaction(db, case_id)
    if case.stage not in AGENT_STAGES:
        raise Conflict("The agent has nothing to do on this case now.")
    log(db, case, "staff", "retry", "Retry")     # a fresh count of rounds
    start_agent(db, case)
    return _commit(db, case)


@_guarded
def approve_plan(db: Session, case_id: int) -> WorkshopCase:
    """Staff approve the plan: its bookings become to-dos, and the mechanic's hours are booked."""
    case = _transaction(db, case_id)
    _in_stage(case, PLAN_REVIEW)
    _idle(case)
    plan = case.plan
    case.stage = APPROVED
    case.repair_hours = Decimal(plan["repair_hours"])
    case.repair_day = date.fromisoformat(plan["repair_starts"])
    # Customers see this date (SPEC §14.9), so it comes from an approved plan, not a draft
    case.ready_estimate = date.fromisoformat(plan["ready_date"]) if plan["ready_date"] else None
    for a in plan["booking_actions"]:
        db.add(CustomerAction(case_id=case.id, rental_id=a["rental_id"], kind=a["action"],
                              why=a["why"], draft=a["email_draft"]))
    log(db, case, "staff", "decision", f"Plan version {plan['version']} approved.")
    return _commit(db, case)


@_guarded
def put_in_maintenance(db: Session, case_id: int) -> WorkshopCase:
    """Available as soon as a case exists: safety doesn't wait for the model (SPEC §14.3)."""
    case = _transaction(db, case_id)
    bike = get_bike(db, case.bike_id)
    if bike.status not in (BikeStatus.available, BikeStatus.maintenance):
        raise Conflict(f"{bike.code} is {bike.status.value} and can't go into maintenance.")
    bike.status, bike.updated_at = BikeStatus.maintenance, utcnow()
    db.add(bike)
    log(db, case, "staff", "decision", "Bike put in maintenance.")
    return _commit(db, case)


@_guarded
def set_ready_estimate(db: Session, case_id: int, ready: Optional[date]) -> WorkshopCase:
    case = _transaction(db, case_id)
    case.ready_estimate = ready
    log(db, case, "staff", "decision", f"Expected back: {ready}.")
    return _commit(db, case)


@_guarded
def progress(db: Session, case_id: int, step: str) -> WorkshopCase:
    """Parts ordered, parts arrived, repair done. Ordering is recorded, nothing is really bought."""
    case = _transaction(db, case_id)
    _in_stage(case, APPROVED, IN_REPAIR)
    if step not in ("ordered", "arrived", "repaired"):
        raise RuleViolation("Step must be ordered, arrived or repaired.")
    if (case.plan or {}).get("kind") not in NEEDS_PARTS:
        raise Conflict("This plan has no repair to record.")
    log(db, case, "staff", "progress", step)
    case.stage = RESCAN if step == "repaired" else IN_REPAIR
    return _commit(db, case)


def _last_scan_passes(db: Session, case: WorkshopCase) -> None:
    """THE SAFETY GATE at the door: the bike's newest scan must not be unfit."""
    if scan_service.done_scans(db, case.bike_id)[0].verdict == scan_service.UNFIT:
        raise Conflict("The last scan says this bike isn't safe to rent. Repair it and scan it again.")


def _close(db: Session, case: WorkshopCase, outcome: str) -> WorkshopCase:
    case.stage, case.outcome, case.ready_estimate, case.repair_day = CLOSED, outcome, None, None
    log(db, case, "staff", "decision", f"Case closed: {outcome}.")
    return _commit(db, case)


@_guarded
def back_in_service(db: Session, case_id: int) -> WorkshopCase:
    """Only with a scan that isn't unfit (SPEC §14.3), and after that scan, not on old data."""
    case = _transaction(db, case_id)
    _in_stage(case, RESCAN, APPROVED)       # APPROVED: a "keep and watch" plan, which never left service
    _last_scan_passes(db, case)
    rescanned = any(e.stage == RESCAN and e.content.startswith("New scan") for e in events_of(db, case.id))
    if case.stage == RESCAN and not rescanned:
        raise Conflict("Run a new scan first: a repaired bike goes back only after it passes.")
    bike = get_bike(db, case.bike_id)
    if bike.status == BikeStatus.maintenance:
        bike.status, bike.updated_at = BikeStatus.available, utcnow()
        db.add(bike)
    return _close(db, case, "rentable")


def _open_bookings(db: Session, bike_id: int) -> list[Rental]:
    return db.exec(select(Rental).where(Rental.bike_id == bike_id, Rental.status.in_(OPEN_STATUSES))).all()


@_guarded
def list_for_sale(db: Session, case_id: int, price: Decimal) -> tuple[WorkshopCase, Bike]:
    """
    A bike's purpose never changes (SPEC §4), so selling a rental bike retires it
    and creates a new sale bike, linked to the old one (SPEC §14.8).
    """
    case = _transaction(db, case_id)
    old = get_bike(db, case.bike_id)
    if _open_bookings(db, old.id):
        raise Conflict(f"{old.code} still has open bookings. Move or cancel them first.")
    plan_kind = (case.plan or {}).get("kind")
    if plan_kind != SELL_AS_IS:
        _last_scan_passes(db, case)
    old.status, old.updated_at = BikeStatus.retired, utcnow()
    db.add(old)
    code = f"S-X{old.code.removeprefix('R-')}"
    new = Bike(code=code, name=old.name, brand=old.brand, category=old.category, frame_size=old.frame_size,
               color=old.color, year=old.year, purpose=Purpose.sale, condition=Condition.used,
               sale_price_chf=money(price), description=f"Ex-rental, serviced in our workshop. {old.description}".strip())
    db.add(new)
    db.flush()
    finance = db.get(BikeFinance, old.id)
    db.add(BikeFinance(bike_id=new.id, purchase_chf=finance.purchase_chf, book_value_chf=finance.book_value_chf,
                       market_value_chf=finance.market_value_chf, replaces_bike_id=old.id))
    case = _close(db, case, "sold")
    db.refresh(new)
    return case, new


@_guarded
def scrap(db: Session, case_id: int) -> WorkshopCase:
    case = _transaction(db, case_id)
    bike = get_bike(db, case.bike_id)
    if _open_bookings(db, bike.id):
        raise Conflict(f"{bike.code} still has open bookings. Move or cancel them first.")
    bike.status, bike.updated_at = BikeStatus.retired, utcnow()
    db.add(bike)
    return _close(db, case, "scrapped")


# ---------------------------------------------------------------- customers

def actions_of(db: Session, case_id: int) -> list[CustomerAction]:
    return db.exec(select(CustomerAction).where(CustomerAction.case_id == case_id).order_by(CustomerAction.id)).all()


def get_action(db: Session, action_id: int) -> CustomerAction:
    action = db.get(CustomerAction, action_id)
    if not action:
        raise NotFound(f"There is no customer action with id {action_id}.")
    return action


def alternatives(db: Session, rental_id: int, ready: Optional[date] = None) -> dict:
    """Free bikes for the same period, with the price change, and other dates (no customer data)."""
    rentals = RentalService()
    rental = db.get(Rental, rental_id)
    if not rental:
        raise NotFound(f"There is no rental with id {rental_id}.")
    bike = get_bike(db, rental.bike_id)
    start, end = rental.start_at, rental.end_at
    found = []
    try:
        free = rentals.available_bikes(db, start, end)
    except RuleViolation:
        free = []       # e.g. it starts today and has passed: no alternative for that period
    for other, _, price in free:
        if other.id != bike.id:
            found.append({"bike_id": other.id, "code": other.code, "name": other.name,
                          "category": other.category.value, "frame_size": other.frame_size.value,
                          "same_category": other.category == bike.category,
                          "price_chf": str(price.total_chf),
                          "price_change_chf": str(money(price.total_chf - rental.quoted_price_chf))})
    found.sort(key=lambda b: (not b["same_category"], abs(float(b["price_change_chf"]))))
    other_dates = []
    day = max(ready or today(), to_local(start).date())
    now = utcnow()
    for step in range(1, 15):
        shift = (day + timedelta(days=step)) - to_local(start).date()
        new_start, new_end = start + shift, end + shift
        try:
            rentals.validate_period(new_start, new_end)
        except RuleViolation:
            continue
        if not rentals._blocking_rental(db, bike.id, new_start, new_end, now):
            other_dates.append({"start_at": to_local(new_start).isoformat(), "end_at": to_local(new_end).isoformat()})
        if len(other_dates) == 3:
            break
    return {"rental_id": rental_id, "same_bike_other_dates": other_dates, "other_bikes_same_dates": found[:6]}


def _action_case(db: Session, action: CustomerAction) -> WorkshopCase:
    return get_case(db, action.case_id)


@_guarded
def send_email(db: Session, action_id: int, text: str) -> CustomerAction:
    """Staff send the email, edited as they like. Our code adds the greeting and the address (SPEC §14.7)."""
    start_write_transaction(db)
    action = get_action(db, action_id)
    if not text.strip():
        raise RuleViolation("The email is empty.")
    rental = db.get(Rental, action.rental_id)
    NotificationService().booking_problem(db, rental, text)
    action.status, action.outcome, action.draft = "done", "email sent", text
    db.add(action)
    log(db, _action_case(db, action), "staff", "action", f"Email sent about booking {rental.id}.")
    db.commit()
    db.refresh(action)
    return action


@_guarded
def finish_action(db: Session, action_id: int, outcome: str) -> CustomerAction:
    """Tick off a to-do, e.g. after a phone call, with what came of it."""
    start_write_transaction(db)
    action = get_action(db, action_id)
    action.status, action.outcome = "done", outcome
    db.add(action)
    log(db, _action_case(db, action), "staff", "action", f"Booking {action.rental_id}: {outcome}")
    db.commit()
    db.refresh(action)
    return action


def move_booking(db: Session, action_id: int, bike_id: int) -> tuple[CustomerAction, Rental]:
    """After the customer agreed: to another free bike, at its price (RentalService checks §5.4)."""
    action = get_action(db, action_id)
    rental = RentalService().move_booking(db, action.rental_id, bike_id)
    return finish_action(db, action_id, f"moved to bike {bike_id}, new price CHF {rental.quoted_price_chf}"), rental


def cancel_booking(db: Session, action_id: int) -> tuple[CustomerAction, Rental]:
    action = get_action(db, action_id)
    rental = RentalService().cancel(db, action.rental_id)
    return finish_action(db, action_id, "booking cancelled"), rental


def db_rental(db: Session, rental_id: int) -> Rental:
    return db.get(Rental, rental_id)


def customer_of(db: Session, rental: Rental) -> Optional[str]:
    """For staff pages only; the agent's tools never call this."""
    user = db.exec(select(User).where(User.user_id == rental.user_id)).first()
    return user.username if user else None
