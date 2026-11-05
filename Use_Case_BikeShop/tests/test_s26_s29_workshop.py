"""
S26-S30 the Workshop (SPEC §11, §14). The AI is scripted here, because CI has no
key: these tests check our code around the model. The real test with
glm-5.3-flash is manual, on the Azurite stack (S27, S31).
"""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, func, select

from api import config
from api.database import engine
from api.jobqueue import queue
from api.models.models import (
    Bike, BikeFinance, BikeStatus, Category, CustomerAction, Job, PartOffer, Purpose, Rental, RentalStatus, Supplier, User,
    WorkshopCase, WorkshopEvent, WorkshopScan,
)
from api.services import llm_service, scan_service, workshop_agent as agent, workshop_service as shop
from api.services.errors import Conflict
from api.services.llm_service import Busy, Reply, ToolCall
from api.timeutils import to_local
from api.tools import workshop_tools as tools
from scripts import seed, seed_history, seed_workshop, worker

from . import test_s23_history as s23
from .conftest import NOW


class FakeAI:
    """Stands in for the model: answers with the replies it was given, in order."""

    def __init__(self, *replies):
        self.replies, self.seen, self.model, self.client = list(replies), [], "fake", self

    def with_options(self, **_):
        return self

    def ask(self, messages):
        self.seen.append(json.dumps(messages, default=str))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def assistant_message(self, reply):
        return [{"role": "assistant", "content": reply.text}]

    def tool_result_messages(self, calls, results):
        return [{"role": "tool", "content": json.dumps(r, default=str)} for r in results]


def asks(*calls, tokens=1000, reasoning="I should look at the scan."):
    return Reply(text="", tokens=tokens, reasoning=reasoning,
                 tool_calls=[ToolCall(f"c{i}", name, inputs) for i, (name, inputs) in enumerate(calls)])


@pytest.fixture
def data(monkeypatch):
    """The whole demo data: seed, a year of history, the Workshop."""
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    seed_history.main()
    seed_workshop.main()


@pytest.fixture
def ai(monkeypatch):
    """Install a scripted model: ai(reply, reply, ...). Returns it, to see what it was sent."""
    def install(*replies):
        fake = FakeAI(*replies)
        monkeypatch.setattr(llm_service, "connect", lambda system, tools, provider, model: fake)
        return fake
    return install


def keys(client, username):
    r = client.post("/auth/generate-key", json={"username": username, "password": f"{username}-pass-123", "name": "t"})
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def bike_id(code):
    with Session(engine) as db:
        return db.exec(select(Bike).where(Bike.code == code)).one().id


def case_of(code):
    with Session(engine) as db:
        return shop.open_case_for(db, bike_id(code)).id


def offer(code, part, quality=None, fastest=True):
    with Session(engine) as db:
        offers = [o for o in shop.offers_for(db, db.get(Bike, bike_id(code)), part)
                  if (o.quality == quality if quality else o.quality != "used")]
        return min(offers, key=lambda o: o.delivery_days if fastest else o.price_chf).id


def run_jobs(limit=30):
    """Let the worker run what's queued, as its loop would."""
    ran = 0
    while ran < limit:
        with Session(engine) as db:
            claimed = queue.claim(db, "test-worker")
        if claimed is None:
            return ran
        worker.run_job(claimed)
        ran += 1
    return ran


def brief_for(code, part, extra=None):
    return {"verdict_sentence": "Not safe to rent.", "what_is_wrong": "A part is worn out and could fail.",
            "options": [{"kind": "repair", "title": "Repair", "what_we_do": "Fit a new part.", "offer_ids": [offer(code, part)]},
                        {"kind": "scrap", "title": "Scrap", "what_we_do": "Take the bike out for parts."}],
            "recommended": "A", "recommended_why": "It is cheap and quick.", **(extra or {})}


URL = "/staff/workshop"


@pytest.fixture
def staff(data, client):
    return keys(client, "staff")


def to_choosing(client, staff, ai, code="R-CITY-05", part="brake_pads_rear"):
    ai(asks(("get_scan_overview", {})), asks(("submit_brief", brief_for(code, part))))
    case_id = case_of(code)
    assert client.post(f"{URL}/cases/{case_id}/analyse", headers=staff).status_code == 200
    run_jobs()
    return case_id


def get(client, staff, case_id):
    return client.get(f"{URL}/cases/{case_id}", headers=staff).json()


def to_plan(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    ai(asks(("submit_position", {"agrees": True, "message": "Good choice."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    ai(asks(("submit_plan", {"summary": "New pads.", "steps": ["Fit the pads"], "booking_actions": []})))
    assert client.post(f"{URL}/cases/{case_id}/agree", headers=staff).status_code == 200
    run_jobs()
    return case_id


# ---------------------------------------------------------------- S26 the data and the machine

def counts():
    with Session(engine) as db:
        return tuple(db.exec(select(func.count()).select_from(t)).one()
                     for t in (Bike, Rental, WorkshopScan, WorkshopCase, Supplier, PartOffer))


def test_runs_once_with_40_rental_bikes(data):
    first = counts()
    seed_workshop.main()
    assert counts() == first
    with Session(engine) as db:
        assert len(scan_service.rental_bikes(db)) == 40
        assert len(db.exec(select(Supplier)).all()) >= 8


def test_every_rental_follows_the_rules(data):
    with Session(engine) as db:
        rentals = db.exec(select(Rental).where(Rental.status != RentalStatus.cancelled)).all()
        guests = db.exec(select(User).where(User.username.like("guest%"))).all()
        booked = {}
        for r in rentals:
            local = [to_local(r.start_at), to_local(r.end_at)]
            for t in local:
                assert shop.is_open(t.date()) and t.minute % 15 == 0
                opens, closes = config.OPENING_HOURS[t.weekday()]
                assert opens <= t.time() <= closes
            assert timedelta(hours=1) <= r.end_at - r.start_at <= timedelta(days=14)
            if r.status in (RentalStatus.booked, RentalStatus.active):
                booked[r.user_id] = booked.get(r.user_id, 0) + 1
        assert not [g for g in guests if booked.get(g.user_id, 0) > 3]
        by_bike = {}
        for r in rentals:
            by_bike.setdefault(r.bike_id, []).append(r)
        for same in by_bike.values():
            same.sort(key=lambda r: r.start_at)
            for a, b in zip(same, same[1:]):
                assert max(a.end_at, a.returned_at or a.end_at) <= b.start_at, f"rentals {a.id} and {b.id} overlap"


def test_short_gaps_and_bookings_ahead(data):
    with Session(engine) as db:
        future = db.exec(select(Rental).where(Rental.status == RentalStatus.booked)).all()
        assert len(future) > 150
        last = max(to_local(r.start_at).date() for r in future)
        assert (last - to_local(NOW).date()).days <= config.MAX_DAYS_AHEAD
        same_day = [(a, b) for a, b in zip(sorted(future, key=lambda r: (r.bike_id, r.start_at)),
                                           sorted(future, key=lambda r: (r.bike_id, r.start_at))[1:])
                    if a.bike_id == b.bike_id and b.start_at - a.end_at < timedelta(hours=6)]
        assert same_day, "there should be turnarounds of a few hours"


def test_planted_patterns_still_hold(data):
    with Session(engine) as db:
        guests = {u.user_id for u in db.exec(select(User).where(User.username.like("guest%"))).all()}
        bikes = {b.id: b for b in db.exec(select(Bike)).all()}
        rentals = [r for r in db.exec(select(Rental)).all() if r.user_id in guests]
        orders = [o for o in db.exec(select(seed_history.Order)).all() if o.user_id in guests]
        from api.models.models import AnalyticsEvent
        events = db.exec(select(AnalyticsEvent)).all()
    s23.test_planted_patterns((bikes, rentals, orders, events))


def test_returned_bikes_have_scans_and_the_newest_wait(data):
    with Session(engine) as db:
        waiting = {db.get(Bike, s.bike_id).code for s in scan_service.waiting_bikes(db)}
        assert len(waiting) == 3
        old = to_local(NOW).date() - timedelta(days=2)
        for bike in scan_service.rental_bikes(db):
            returned = db.exec(select(Rental).where(Rental.bike_id == bike.id, Rental.status == RentalStatus.returned)
                               .order_by(Rental.returned_at.desc())).first()
            if returned and to_local(returned.returned_at).date() <= old and bike.code not in waiting:
                assert scan_service.done_scans(db, bike.id), bike.code


def test_the_safety_gate():
    reading = dict(scan_service.CATALOGUE[0])          # crack depth: 0 is good, 0.3 watch, 0.8 unfit
    assert scan_service.verdict(scan_service.grade([{**reading, "value": .1}])) == "fit"
    assert scan_service.verdict(scan_service.grade([{**reading, "value": .3}])) == "watch"
    assert scan_service.verdict(scan_service.grade([{**reading, "value": .8}])) == "unfit"
    trend = scan_service.grade([{**reading, "value": .2}], [{**reading, "value": .05}])
    assert trend[0]["status"] == "trend" and scan_service.verdict(trend) == "watch"


def test_each_planted_case_has_the_verdict_of_its_answer_key(data):
    expected = {"R-EBIKE-08": "unfit", "R-CITY-05": "unfit", "R-MTB-04": "watch", "R-ROAD-03": "unfit",
                "R-EBIKE-09": "unfit", "R-GRAV-03": "unfit", "R-ROAD-04": "unfit", "R-GRAV-04": "unfit",
                "R-CARGO-03": "unfit", "R-CITY-07": "watch"}
    with Session(engine) as db:
        for code, verdict in expected.items():
            case = shop.open_case_for(db, bike_id(code))
            assert shop.case_scan(db, case).verdict == verdict, code


def test_the_planted_trade_offs_are_real(data):
    with Session(engine) as db:
        road = shop.open_case_for(db, bike_id("R-ROAD-03"))                      # D4
        booking = shop.upcoming_bookings(db, road.bike_id)[0]
        quick = shop.priced_option(db, road, shop.REPAIR, [offer("R-ROAD-03", "wheel_rear", "new_oem")])
        cheap = shop.priced_option(db, road, shop.REPAIR, [offer("R-ROAD-03", "wheel_rear", "new_aftermarket", fastest=False)])
        assert booking.id not in quick["bookings_affected"] and booking.id in cheap["bookings_affected"]
        assert Decimal(cheap["cost_chf"]) < Decimal(quick["cost_chf"])

        pads = shop.open_case_for(db, bike_id("R-CITY-05"))                      # D2: on the shelf, no clash
        assert shop.priced_option(db, pads, shop.REPAIR, [offer("R-CITY-05", "brake_pads_rear")])["bookings_affected"] == []

        old = shop.open_case_for(db, bike_id("R-EBIKE-09"))                      # D5
        battery = shop.priced_option(db, old, shop.REPAIR, [offer("R-EBIKE-09", "battery")])
        assert Decimal(battery["cost_chf"]) > shop.income_last_year(db, old.bike_id)

        second = shop.open_case_for(db, bike_id("R-ROAD-04"))                    # D7: the first repair fills the week
        parts = [offer("R-ROAD-04", "bottom_bracket", "new_oem"), offer("R-ROAD-04", "crank", "new_oem")]
        priced = shop.priced_option(db, second, shop.REPAIR, parts)
        assert priced["days_waiting_for_mechanic"] > 0 and priced["bookings_affected"]

        cargo = shop.alternatives(db, shop.upcoming_bookings(db, bike_id("R-CARGO-03"))[0].id)   # D9
        others = cargo["other_bikes_same_dates"]
        assert others and not [b for b in others if b["same_category"]]

        city = shop.economics(db, bike_id("R-CITY-07"), Decimal("120"))          # D10
        assert city["repair_and_sell"]["list_price_chf"] == "560.00" and not city["repair_and_sell"]["below_target"]


def test_a_live_scan_needs_no_ai_and_finds_the_problem(client, staff):
    with Session(engine) as db:
        jobs = db.exec(select(func.count()).select_from(Job)).one()
    r = client.post(f"{URL}/bikes/{bike_id('R-EBIKE-10')}/scan", headers=staff)
    assert r.status_code == 200 and r.json()["verdict"] == "unfit" and r.json()["case_id"]
    with Session(engine) as db:
        assert db.exec(select(func.count()).select_from(Job)).one() == jobs
        assert len(scan_service.waiting_bikes(db)) == 2


def test_a_clean_scan_closes_without_ai(client, staff):
    body = client.post(f"{URL}/bikes/{bike_id('R-MTB-05')}/scan", headers=staff).json()
    assert body["verdict"] == "fit"
    with Session(engine) as db:
        assert db.get(WorkshopCase, body["case_id"]).outcome == "no_finding"


def test_the_workshop_is_for_staff_only(client, data):
    customer = keys(client, "customer")
    assert client.get(URL, headers=customer).status_code == 403
    assert client.post(f"{URL}/bikes/1/scan", headers=customer).status_code == 403


def test_the_hidden_faults_never_reach_a_page(client, staff):
    assert "faults" not in client.get(f"{URL}/cases/{case_of('R-GRAV-03')}", headers=staff).text
    scan = client.post(f"{URL}/bikes/{bike_id('R-EBIKE-10')}/scan", headers=staff).json()
    assert "faults" not in scan


# ---------------------------------------------------------------- S27 the agent

def test_the_rounds_run_as_separate_jobs_and_reach_the_brief(client, staff, ai):
    fake = ai(asks(("get_scan_overview", {})), asks(("get_group_readings", {"group": "brakes"})),
              asks(("submit_brief", brief_for("R-CITY-05", "brake_pads_rear"))))
    case_id = case_of("R-CITY-05")
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    assert run_jobs() == 3
    body = get(client, staff, case_id)
    assert body["stage"] == "choosing" and body["agent_state"] == "idle"
    assert [c["key"] for c in body["brief"]["options"]] == ["A", "B"]
    assert body["brief"]["options"][0]["cost_chf"] and body["brief"]["options"][0]["ready_date"]
    assert body["brief"]["options"][0]["scores"]["safety"] == 5
    rounds = [e for e in body["events"] if e["kind"] == "round"]
    assert len(rounds) == 3 and rounds[0]["reasoning"] and rounds[0]["tokens"] == 1000
    assert "verdict_from_the_safety_gate" in fake.seen[-1]   # the conversation is rebuilt from the database


def test_a_chat_job_runs_between_rounds(client, staff, ai):
    ai(asks(("get_scan_overview", {})), asks(("submit_brief", brief_for("R-CITY-05", "brake_pads_rear"))))
    client.post(f"{URL}/cases/{case_of('R-CITY-05')}/analyse", headers=staff)
    with Session(engine) as db:
        queue.enqueue(db, "send_email", {"to": "x@y.test", "subject": "s", "text": "t"})
        db.commit()
    order = []
    while True:
        with Session(engine) as db:
            claimed = queue.claim(db, "test-worker")
        if claimed is None:
            break
        order.append(claimed.kind)
        worker.run_job(claimed)
    assert order == ["workshop_step", "send_email", "workshop_step"]


def test_a_repeated_job_changes_nothing(client, staff, ai):
    ai(asks(("get_scan_overview", {})))
    case_id = case_of("R-CITY-05")
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    assert agent.workshop_step({"case_id": case_id, "step_no": 0, "retries": 0}) == {"skipped": "an older step"}


def test_busy_waits_and_loses_nothing(client, staff, ai):
    ai(Busy(), asks(("submit_brief", brief_for("R-CITY-05", "brake_pads_rear"))))
    case_id = case_of("R-CITY-05")
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    run_jobs()
    body = get(client, staff, case_id)
    assert body["agent_state"] == "waiting" and body["agent_note"] == agent.WAITING_NOTE
    with Session(engine) as db:
        waiting = db.exec(select(Job).where(Job.status == "queued")).one()
        waiting.run_after = shop.utcnow()
        db.add(waiting)
        db.commit()
    run_jobs()
    assert get(client, staff, case_id)["stage"] == "choosing"


def test_the_budget_keeps_rounds_below_the_limits(client, staff, ai):
    case_id = case_of("R-CITY-05")
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_id)
        assert agent.budget_wait(db, case) == 0
        db.add_all([WorkshopEvent(case_id=case_id, stage="analysing", author="agent", kind="round", tokens=100)
                    for _ in range(config.WORKSHOP_REQUESTS_PER_MINUTE)])
        db.commit()
        assert agent.budget_wait(db, case) > 0
    assert config.WORKSHOP_REQUESTS_PER_MINUTE < 30 and config.WORKSHOP_TOKENS_PER_MINUTE < 150_000


def test_a_token_heavy_minute_also_waits(client, staff):
    case_id = case_of("R-CITY-05")
    with Session(engine) as db:
        db.add(WorkshopEvent(case_id=case_id, stage="analysing", author="agent", kind="round", tokens=config.WORKSHOP_TOKENS_PER_MINUTE))
        db.commit()
        assert agent.budget_wait(db, db.get(WorkshopCase, case_id)) > 0


def test_a_failing_model_ends_in_retry_not_a_stuck_page(client, staff, ai, monkeypatch):
    monkeypatch.setattr(config, "WORKSHOP_RETRY_SECONDS", 0)
    ai(ValueError("broken answer"))
    case_id = case_of("R-CITY-05")
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    run_jobs()
    assert get(client, staff, case_id)["agent_state"] == "failed"
    ai(asks(("submit_brief", brief_for("R-CITY-05", "brake_pads_rear"))))
    assert client.post(f"{URL}/cases/{case_id}/retry", headers=staff).status_code == 200
    run_jobs()
    assert get(client, staff, case_id)["stage"] == "choosing"


def test_an_endless_agent_stops_after_8_rounds(client, staff, ai):
    fake = ai(asks(("get_scan_overview", {})))
    case_id = case_of("R-CITY-05")
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    run_jobs()
    assert len(fake.seen) == config.WORKSHOP_MAX_ROUNDS
    assert get(client, staff, case_id)["agent_state"] == "failed"


def test_retry_really_runs_after_the_agent_ran_out_of_rounds(client, staff, ai):
    ai(asks(("get_scan_overview", {})))
    case_id = case_of("R-CITY-05")
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    run_jobs()
    assert get(client, staff, case_id)["agent_state"] == "failed"
    ai(asks(("submit_brief", brief_for("R-CITY-05", "brake_pads_rear"))))
    client.post(f"{URL}/cases/{case_id}/retry", headers=staff)
    run_jobs()
    assert get(client, staff, case_id)["stage"] == "choosing"


@pytest.mark.parametrize("change, error", [
    ({"verdict_sentence": "word " * 26}, "verdict_sentence"),
    ({"what_is_wrong": "word " * 61}, "what_is_wrong"),
    ({"recommended": "Z"}, "recommended"),
])
def test_a_brief_breaking_the_limits_is_refused(data, change, error):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-CITY-05"))
        result = shop.submit_brief(db, case, brief_for("R-CITY-05", "brake_pads_rear", change))
        assert error in result["error"] and case.brief is None


@pytest.mark.parametrize("kind", ["keep_watch", "sell_as_is"])
def test_an_option_leaving_a_bike_unfit_is_refused(data, kind):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-CITY-05"))
        brief = brief_for("R-CITY-05", "brake_pads_rear")
        brief["options"][1] = {"kind": kind, "title": "Carry on", "what_we_do": "Leave it as it is."}
        assert "unfit" in shop.submit_brief(db, case, brief)["error"]


def test_a_repair_missing_an_unfit_part_is_refused(data):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-GRAV-04"))
        brief = brief_for("R-GRAV-04", "tyre_rear")
        assert "brake_caliper_front" in shop.submit_brief(db, case, brief)["error"]


def test_a_used_part_on_a_safety_part_is_refused(data):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-GRAV-04"))
        used = offer("R-GRAV-04", "brake_caliper_front", "used")
        brief = brief_for("R-GRAV-04", "brake_caliper_front")
        brief["options"][0]["offer_ids"] = [used]
        assert "used" in shop.submit_brief(db, case, brief)["error"]


def test_a_low_margin_chf_comes_from_code_not_the_agent(data):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-CITY-05"))
        brief = brief_for("R-CITY-05", "brake_pads_rear")
        brief["options"][0]["cost_chf"], brief["options"][0]["ready_date"] = "1.00", "2020-01-01"
        assert shop.submit_brief(db, case, brief)["ok"]
        card = case.brief["options"][0]
        assert card["cost_chf"] != "1.00" and card["ready_date"] != "2020-01-01"


def test_no_tool_gives_the_agent_a_person(data):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-EBIKE-08"))     # booked by the demo customer
        rental = shop.upcoming_bookings(db, case.bike_id)[0]
        user = db.exec(select(User).where(User.user_id == rental.user_id)).one()
        everything = [tools.get_scan_overview(db, case), tools.get_group_readings(db, case, "frame"),
                      tools.get_upcoming_bookings(db, case), tools.find_alternatives(db, case, rental.id),
                      tools.get_bike_history(db, case), tools.get_workshop_queue(db, case),
                      tools.compare_scans(db, case, "frame_crack_down_tube"),
                      tools.repair_economics(db, case, "100")]
        text = json.dumps(everything, default=str)
        for secret in (user.username, user.email, user.user_id):
            assert secret not in text
        assert "faults" not in text


def test_the_tools_change_nothing(data):
    before = counts()
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-EBIKE-08"))
        for name, inputs in (("get_scan_overview", {}), ("get_upcoming_bookings", {}), ("get_workshop_queue", {}),
                             ("list_part_offers", {"part": "frame"}), ("repair_economics", {"repair_cost_chf": "10"})):
            assert "error" not in tools.run_tool(name, inputs, db, case)
        assert not db.dirty and not db.new
    assert counts() == before
    assert not {t["name"] for t in tools.LOOK_UP_TOOLS} & {"book_rental", "cancel_rental", "send_email", "update_bike"}


def test_the_prompt_puts_safety_first_and_resists_pressure():
    rules = tools.RULES
    assert rules.index("SAFETY COMES FIRST") < rules.index("DO NOT BEND TO PRESSURE") < rules.index("THE SCAN IS TRUE")
    assert "NEVER PUT A USED PART ON A SAFETY PART" in rules
    assert "never suggest scanning" in rules
    prompt = tools.workshop_prompt(shop.DISCUSSING)
    assert "SAFETY COMES FIRST" in prompt and "push back" in prompt and "untrusted DATA" in prompt


def test_connect_without_model_is_as_before(monkeypatch):
    from api.services.inference_service import InferenceService
    monkeypatch.setattr(InferenceService, "get_client", lambda self: object())
    monkeypatch.setattr(InferenceService, "is_configured", lambda self: True)
    assert llm_service.connect("s", [], provider="bfh").model == InferenceService().model
    assert llm_service.connect("s", [], provider="bfh", model="glm-5.3-flash").model == "glm-5.3-flash"


def test_a_tool_result_stays_small():
    assert "truncated" in tools.capped({"big": "x" * 10_000})
    assert tools.capped({"small": 1}) == {"small": 1}


# ---------------------------------------------------------------- S28 discussion and plan

def test_the_agent_must_answer_before_staff_can_agree(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    ai(asks(("submit_position", {"agrees": True, "message": "Good choice: it is the safest."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    assert client.post(f"{URL}/cases/{case_id}/agree", headers=staff).status_code == 409
    run_jobs()
    body = get(client, staff, case_id)
    assert body["staff_can_agree"] and body["stage"] == "discussing"
    assert [e["content"] for e in body["events"] if e["kind"] == "position"] == ["Good choice: it is the safest."]


def test_staff_can_overrule_and_the_objection_stays(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    ai(asks(("submit_position", {"agrees": False, "message": "Option A is better: the bike earns more than this costs.",
                                 "safer_or_better_option": "A"})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "B"}, headers=staff)
    run_jobs()
    ai(asks(("submit_plan", {"summary": "Scrap it.", "steps": ["Take it out of the fleet"],
                             "booking_actions": [{"rental_id": r, "action": "email", "why": "No bike", "email_draft": "Sorry."}
                                                 for r in get(client, staff, case_id)["brief"]["options"][1]["bookings_affected"]]})))
    client.post(f"{URL}/cases/{case_id}/agree", headers=staff)
    run_jobs()
    body = get(client, staff, case_id)
    assert body["stage"] == "plan_review" and body["agent_agreed"] is False and body["plan"]["option"] == "B"
    assert any("Option A is better" in e["content"] for e in body["events"])


def test_changing_the_option_makes_the_agent_answer_again(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(asks(("submit_position", {"agrees": True, "message": "Fine."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "B"}, headers=staff)
    assert not get(client, staff, case_id)["staff_can_agree"]
    run_jobs()
    assert len(fake.seen) == 2 and get(client, staff, case_id)["staff_can_agree"]


def test_a_discussion_can_go_on(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(asks(("submit_position", {"agrees": True, "message": "Yes."})),
              Reply(text="Because the reading is past the limit.", tokens=10))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    client.post(f"{URL}/cases/{case_id}/messages", json={"text": "Why?"}, headers=staff)
    run_jobs()
    assert "Why?" in fake.seen[-1]
    texts = [e["content"] for e in get(client, staff, case_id)["events"] if e["kind"] == "message"]
    assert texts == ["Why?", "Because the reading is past the limit."]


def test_a_plan_can_be_revised_and_versions_stay(client, staff, ai):
    case_id = to_plan(client, staff, ai)
    assert get(client, staff, case_id)["plan_version"] == 1
    ai(asks(("submit_plan", {"summary": "New pads today.", "steps": ["Fit the pads"], "booking_actions": []})))
    client.post(f"{URL}/cases/{case_id}/messages", json={"text": "Can it be today?"}, headers=staff)
    run_jobs()
    body = get(client, staff, case_id)
    assert body["plan_version"] == 2
    assert [e["data"]["version"] for e in body["events"] if e["kind"] == "plan"] == [1, 2]


def test_customers_see_a_date_only_from_an_approved_plan(client, staff, ai):
    case_id = to_plan(client, staff, ai)
    assert get(client, staff, case_id)["ready_estimate"] is None
    client.post(f"{URL}/cases/{case_id}/approve-plan", headers=staff)
    assert get(client, staff, case_id)["ready_estimate"]


def test_the_most_urgent_case_comes_first(client, staff):
    cases = client.get(URL, headers=staff).json()["cases"]
    verdicts = [c["verdict"] for c in cases]
    assert verdicts == sorted(verdicts, key=lambda v: v != "unfit")
    unsafe = [c["next_booking"] for c in cases if c["verdict"] == "unfit" and c["next_booking"]]
    assert unsafe == sorted(unsafe)


def test_a_plan_must_cover_every_affected_booking(data):
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-EBIKE-08"))
        assert shop.submit_brief(db, case, brief_for("R-EBIKE-08", "frame"))["ok"]
        case.chosen_option = "A"
        result = shop.submit_plan(db, case, {"summary": "s", "steps": ["x"], "booking_actions": []})
        assert "no action yet" in result["error"]


def test_the_message_limit_asks_staff_to_decide(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    ai(Reply(text="Fine.", tokens=1))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    for _ in range(config.WORKSHOP_MAX_STAFF_MESSAGES):
        assert client.post(f"{URL}/cases/{case_id}/messages", json={"text": "Hm?"}, headers=staff).status_code == 200
        run_jobs()
    assert client.post(f"{URL}/cases/{case_id}/messages", json={"text": "Hm?"}, headers=staff).status_code == 409


def test_discussion_prompts_stay_small(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(Reply(text="ok", tokens=1))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    for n in range(8):
        client.post(f"{URL}/cases/{case_id}/messages", json={"text": f"message {n}"}, headers=staff)
        run_jobs()
    assert "message 7" in fake.seen[-1] and "message 0" not in fake.seen[-1]
    assert "readings" not in json.loads(fake.seen[-1])[0]["content"].split('"options"')[0]


def test_staff_can_write_while_the_agent_is_working_and_nothing_is_lost(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(asks(("submit_position", {"agrees": True, "message": "Answering the newest message."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)      # the agent is working
    r = client.post(f"{URL}/cases/{case_id}/messages", json={"text": "One more thing."}, headers=staff)
    assert r.status_code == 200 and r.json()["agent_state"] == "working"
    run_jobs()
    assert len(fake.seen) == 1 and "One more thing." in fake.seen[0]    # the older job stood aside
    body = get(client, staff, case_id)
    assert body["staff_can_agree"] and [e["content"] for e in body["events"] if e["kind"] == "position"] == ["Answering the newest message."]


def test_an_answer_overtaken_by_a_new_message_is_dropped(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    late = asks(("submit_position", {"agrees": True, "message": "Too late."}))

    class Overtaken(FakeAI):
        def ask(self, messages):
            with Session(engine) as other:
                shop.say(other, case_id, "Wait, a new thought.")
            return late

    with Session(engine) as db:
        agent.one_round(db, db.get(WorkshopCase, case_id), Overtaken(late))
        db.commit()
    events = get(client, staff, case_id)["events"]
    assert "Too late." not in [e["content"] for e in events]


def test_a_failed_agent_doesnt_lock_the_human_out(client, staff, ai, monkeypatch):
    monkeypatch.setattr(config, "WORKSHOP_RETRY_SECONDS", 0)
    case_id = to_choosing(client, staff, ai)
    ai(ValueError("broken answer"))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    body = get(client, staff, case_id)
    assert body["agent_state"] == "failed" and body["staff_can_agree"]
    fake = ai(Reply(text="Sorry, here I am.", tokens=1))
    assert client.post(f"{URL}/cases/{case_id}/messages", json={"text": "Hello?"}, headers=staff).status_code == 200
    run_jobs()
    assert "Hello?" in fake.seen[0] and get(client, staff, case_id)["agent_state"] == "idle"
    ai(ValueError("broken answer"))
    client.post(f"{URL}/cases/{case_id}/messages", json={"text": "Again?"}, headers=staff)
    run_jobs()
    ai(asks(("submit_plan", {"summary": "New pads.", "steps": ["Fit them"], "booking_actions": []})))
    assert client.post(f"{URL}/cases/{case_id}/agree", headers=staff).status_code == 200     # the final word


def test_a_lost_job_shows_up_instead_of_a_page_that_waits_forever(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    ai(asks(("submit_position", {"agrees": True, "message": "Yes."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    with Session(engine) as db:
        job = db.exec(select(Job).where(Job.status == "queued")).one()
        job.status = "failed"       # as after a restart
        db.add(job)
        db.commit()
    body = get(client, staff, case_id)
    assert body["agent_state"] == "failed" and body["agent_note"]


def test_the_model_call_has_hard_limits(monkeypatch):
    class Client:
        def with_options(self, **options):
            self.options = options
            return self

    from api.services.inference_service import InferenceService
    client = Client()
    monkeypatch.setattr(InferenceService, "get_client", lambda self: client)
    ai = agent.connect_agent(shop.DISCUSSING)
    assert client.options == {"timeout": config.WORKSHOP_CALL_TIMEOUT_SECONDS, "max_retries": 0}
    assert ai.max_tokens == config.WORKSHOP_CHAT_REPLY_TOKENS and ai.model == config.WORKSHOP_MODEL
    assert agent.connect_agent(shop.ANALYSING).max_tokens == config.WORKSHOP_MAX_REPLY_TOKENS


def test_a_discussion_answers_from_the_facts_without_investigating_again(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(asks(("submit_position", {"agrees": True, "message": "Yes."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    first = json.loads(json.loads(fake.seen[0])[0]["content"])
    assert first["scan_findings"] and first["options"]
    names = {t["name"] for t in tools.tools_for(shop.DISCUSSING)}
    assert "submit_position" in names and not names & {"get_scan_overview", "get_group_readings", "list_part_offers"}


def test_a_stuck_discussion_stops_quickly(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(asks(("repair_economics", {"repair_cost_chf": "10"})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    assert len(fake.seen) == config.WORKSHOP_CHAT_ROUNDS
    assert get(client, staff, case_id)["staff_can_agree"]       # failed, and the human can go on


def approved_with(client, staff, ai, code, kind):
    """A case whose approved plan is `kind`, for a bike with no affected bookings to resolve."""
    case_id = case_of(code)
    options = [{"kind": kind, "title": "This", "what_we_do": "Do this."},
               {"kind": "scrap", "title": "Scrap", "what_we_do": "Keep the parts."}]
    ai(asks(("submit_brief", {**brief_for(code, "chain"), "options": options})))
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    run_jobs()
    ai(Reply(text="Fine.", tokens=1))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    ai(asks(("submit_plan", {"summary": "This.", "steps": ["Do it"], "booking_actions": []})))
    client.post(f"{URL}/cases/{case_id}/agree", headers=staff)
    run_jobs()
    assert client.post(f"{URL}/cases/{case_id}/approve-plan", headers=staff).status_code == 200
    return case_id


def test_keep_and_watch_stays_in_service(client, staff, ai):
    case_id = approved_with(client, staff, ai, "R-MTB-04", "keep_watch")
    body = client.post(f"{URL}/cases/{case_id}/back-in-service", headers=staff).json()
    assert body["stage"] == "closed" and body["bike_status"] == "available"


# ---------------------------------------------------------------- S29 staff actions

def test_maintenance_works_before_any_ai_answer(client, staff):
    case_id = case_of("R-EBIKE-08")
    body = client.post(f"{URL}/cases/{case_id}/maintenance", headers=staff).json()
    assert body["bike_status"] == "maintenance" and body["stage"] == "open"


def test_a_bike_stays_out_until_a_rescan_passes(client, staff, ai):
    case_id = to_plan(client, staff, ai)
    client.post(f"{URL}/cases/{case_id}/approve-plan", headers=staff)
    client.post(f"{URL}/cases/{case_id}/maintenance", headers=staff)
    assert client.post(f"{URL}/cases/{case_id}/back-in-service", headers=staff).status_code == 409   # still unfit
    for step in ("ordered", "arrived", "repaired"):
        assert client.post(f"{URL}/cases/{case_id}/progress", json={"step": step}, headers=staff).status_code == 200
    assert client.post(f"{URL}/cases/{case_id}/back-in-service", headers=staff).status_code == 409   # no rescan yet
    scan = client.post(f"{URL}/bikes/{bike_id('R-CITY-05')}/scan", headers=staff).json()
    assert scan["verdict"] == "fit"
    body = client.post(f"{URL}/cases/{case_id}/back-in-service", headers=staff).json()
    assert body["stage"] == "closed" and body["outcome"] == "rentable" and body["bike_status"] == "available"


def test_the_scan_is_trusted_no_second_scan_before_a_repair(client, staff):
    r = client.post(f"{URL}/bikes/{bike_id('R-EBIKE-08')}/scan", headers=staff)
    assert r.status_code == 409 and "trusted" in r.json()["detail"]
    with Session(engine) as db:
        assert scan_service.verdict(shop.case_scan(db, shop.open_case_for(db, bike_id("R-EBIKE-08"))).readings) == "unfit"


def test_rescan_is_not_an_option(data):
    assert "rescan" not in shop.OPTION_KINDS
    assert "rescan" not in tools.SUBMIT_BRIEF["input_schema"]["properties"]["options"]["items"]["properties"]["kind"]["enum"]
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-CITY-05"))
        brief = brief_for("R-CITY-05", "brake_pads_rear")
        brief["options"][1] = {"kind": "rescan", "title": "Scan first", "what_we_do": "Check it."}
        assert "kind must be" in shop.submit_brief(db, case, brief)["error"]


@pytest.mark.parametrize("words", [
    "Rescan first", "Let us re-scan the tube", "It could be a sensor fault", "maybe a false alarm",
    "Scan it again today", "This may be an error", "Recheck the reading", "a faulty reading",
])
def test_words_that_doubt_the_machine_are_refused(data, words):
    assert shop.doubts_the_scan(words)
    with Session(engine) as db:
        case = db.get(WorkshopCase, case_of("R-CITY-05"))
        result = shop.submit_brief(db, case, brief_for("R-CITY-05", "brake_pads_rear", {"what_is_wrong": words}))
        assert "always right" in result["error"]


@pytest.mark.parametrize("words", ["The rear brake pad is worn out.", "Torque sensor error is high.", "New pads, ready today."])
def test_normal_words_pass(words):
    assert not shop.doubts_the_scan(words)


def test_the_agent_cannot_doubt_the_scan_in_a_discussion(client, staff, ai):
    case_id = to_choosing(client, staff, ai)
    fake = ai(asks(("submit_position", {"agrees": False, "message": "Rescan first, it may be a sensor error."})),
              Reply(text="It could be a false alarm.", tokens=1),
              asks(("submit_position", {"agrees": True, "message": "The reading is past its limit, so we repair."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    said = [e["content"] for e in get(client, staff, case_id)["events"] if e["kind"] in ("position", "message")]
    assert said == ["The reading is past its limit, so we repair."] and len(fake.seen) == 3


def plan_with_action(client, staff, ai, kind="email"):
    """D1: the bike is booked by the demo customer, with an action for each booking."""
    case_id = case_of("R-EBIKE-08")
    ai(asks(("submit_brief", brief_for("R-EBIKE-08", "frame"))))
    client.post(f"{URL}/cases/{case_id}/analyse", headers=staff)
    run_jobs()
    affected = get(client, staff, case_id)["brief"]["options"][0]["bookings_affected"]
    ai(asks(("submit_position", {"agrees": True, "message": "Yes."})))
    client.post(f"{URL}/cases/{case_id}/choose", json={"option": "A"}, headers=staff)
    run_jobs()
    ai(asks(("submit_plan", {"summary": "New frame.", "steps": ["Fit it"], "booking_actions": [
        {"rental_id": r, "action": kind, "why": "The bike is unsafe.", "email_draft": "Your bike has a problem."} for r in affected]})))
    client.post(f"{URL}/cases/{case_id}/agree", headers=staff)
    run_jobs()
    assert client.post(f"{URL}/cases/{case_id}/approve-plan", headers=staff).status_code == 200
    return case_id, get(client, staff, case_id)["actions"]


def test_staff_send_the_email_and_it_goes_through_the_queue(client, staff, ai):
    _, actions = plan_with_action(client, staff, ai)
    assert actions and actions[0]["draft"] == "Your bike has a problem."
    r = client.post(f"{URL}/actions/{actions[0]['id']}/email", json={"text": "Dear customer, your bike is unsafe.\nTry bike 7."}, headers=staff)
    assert r.status_code == 200 and r.json()["status"] == "done"
    with Session(engine) as db:
        jobs = db.exec(select(Job).where(Job.kind == "send_email")).all()
        assert any("your bike is unsafe" in j.payload["text"] and "Hello" in j.payload["text"] for j in jobs)


def test_moving_a_booking_checks_the_bike_and_shows_the_price(client, staff, ai):
    _, actions = plan_with_action(client, staff, ai, "move")
    action = actions[0]
    options = client.get(f"{URL}/actions/{action['id']}/alternatives", headers=staff).json()
    other = options["other_bikes_same_dates"][0]
    assert "price_change_chf" in other
    r = client.post(f"{URL}/actions/{action['id']}/move", json={"bike_id": other["bike_id"]}, headers=staff)
    assert r.status_code == 200 and r.json()["bike_id"] == other["bike_id"]
    assert r.json()["quoted_price_chf"] == other["price_chf"]


def test_moving_to_a_taken_bike_is_a_conflict(client, staff, ai):
    _, actions = plan_with_action(client, staff, ai, "move")
    with Session(engine) as db:
        rental = db.get(Rental, actions[0]["rental_id"])
        taken = db.exec(select(Rental).where(Rental.bike_id != rental.bike_id, Rental.status == RentalStatus.booked,
                                             Rental.start_at < rental.end_at, Rental.end_at > rental.start_at)).first()
        target, bike_before = taken.bike_id, rental.bike_id
    r = client.post(f"{URL}/actions/{actions[0]['id']}/move", json={"bike_id": target}, headers=staff)
    assert r.status_code == 409
    with Session(engine) as db:
        assert db.get(Rental, actions[0]["rental_id"]).bike_id == bike_before


def test_cancel_and_call_actions(client, staff, ai):
    _, actions = plan_with_action(client, staff, ai, "cancel")
    r = client.post(f"{URL}/actions/{actions[0]['id']}/cancel", headers=staff)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    if len(actions) > 1:
        r = client.post(f"{URL}/actions/{actions[1]['id']}/done", json={"outcome": "Called: fine."}, headers=staff)
        assert r.json()["outcome"] == "Called: fine."


def test_selling_retires_the_bike_and_keeps_its_purpose(client, staff):
    case_id = case_of("R-CITY-07")
    assert client.post(f"{URL}/cases/{case_id}/list-for-sale", json={"price_chf": "560"}, headers=staff).status_code == 409   # booked
    with Session(engine) as db:
        for rental in shop.upcoming_bookings(db, bike_id("R-CITY-07")):
            shop.RentalService().cancel(db, rental.id)
    r = client.post(f"{URL}/cases/{case_id}/list-for-sale", json={"price_chf": "560"}, headers=staff)
    assert r.status_code == 200
    sale = r.json()["sale_bike"]
    assert sale["purpose"] == "sale" and sale["condition"] == "used" and sale["sale_price_chf"] == "560.00"
    with Session(engine) as db:
        old = db.get(Bike, bike_id("R-CITY-07"))
        assert old.status == BikeStatus.retired and old.purpose == Purpose.rental
        assert db.get(BikeFinance, sale["id"]).replaces_bike_id == old.id


def test_the_sale_price_keeps_a_quarter_of_the_price():
    assert shop.sale_price(Decimal("300"), Decimal("150"), Decimal("900"))["list_price_chf"] == "600.00"
    capped = shop.sale_price(Decimal("300"), Decimal("150"), Decimal("500"))
    assert capped["list_price_chf"] == "500.00" and capped["below_target"]


def test_an_unfit_bike_cannot_be_listed_for_sale(client, staff):
    case_id = case_of("R-EBIKE-09")
    with Session(engine) as db:
        for rental in shop.upcoming_bookings(db, bike_id("R-EBIKE-09")):
            shop.RentalService().cancel(db, rental.id)
    assert client.post(f"{URL}/cases/{case_id}/list-for-sale", json={"price_chf": "900"}, headers=staff).status_code == 409


def test_the_agent_has_no_way_to_act():
    menu = {t["name"] for t in tools.LOOK_UP_TOOLS + [tools.SUBMIT_BRIEF, tools.SUBMIT_POSITION, tools.SUBMIT_PLAN]}
    assert not {n for n in menu if any(w in n for w in ("send", "move", "cancel", "update", "set_", "retire", "book_"))}


# ---------------------------------------------------------------- S30 availability for customers

def test_a_bike_in_repair_stays_listed_with_its_date(client, staff, ai):
    customer = keys(client, "customer")
    case_id = case_of("R-CITY-07")
    client.post(f"{URL}/cases/{case_id}/maintenance", headers=staff)
    client.post(f"{URL}/cases/{case_id}/ready-estimate", json={"ready_estimate": "2026-11-20"}, headers=staff)
    listed = client.get("/api/bikes", params={"purpose": "rental"}, headers=customer).json()
    bike = next(b for b in listed if b["code"] == "R-CITY-07")
    assert bike["status"] == "maintenance" and bike["ready_estimate"] == "2026-11-20"
    assert client.get(f"/api/bikes/{bike['id']}", headers=customer).json()["ready_estimate"] == "2026-11-20"


def test_the_filter_only_filters(client, staff):
    customer = keys(client, "customer")
    client.post(f"{URL}/cases/{case_of('R-CITY-07')}/maintenance", headers=staff)
    everything = client.get("/api/bikes", params={"purpose": "rental"}, headers=customer).json()
    repairs = client.get("/api/bikes", params={"purpose": "rental", "availability": "maintenance"}, headers=customer).json()
    free = client.get("/api/bikes", params={"purpose": "rental", "availability": "available"}, headers=customer).json()
    assert {b["status"] for b in repairs} == {"maintenance"} and {b["status"] for b in free} == {"available"}
    assert len(repairs) + len(free) == len(everything)


def test_booking_logic_is_unchanged_for_a_bike_in_repair(client, staff):
    customer = keys(client, "customer")
    code = "R-MTB-06"
    case = client.post(f"{URL}/bikes/{bike_id(code)}/scan", headers=staff).json()
    with Session(engine) as db:
        bike = db.get(Bike, bike_id(code))
        bike.status = BikeStatus.maintenance
        db.add(bike)
        db.commit()
    day = "2026-11-28"      # a Saturday, far from the seeded rentals' first weeks
    period = {"start_at": f"{day}T10:00", "end_at": f"{day}T12:00"}
    free = client.get("/api/availability", params=period, headers=customer).json()["bikes"]
    assert bike_id(code) not in [b["bike"]["id"] for b in free]
    r = client.post("/api/rentals", json={"bike_id": bike_id(code), **period}, headers=customer)
    assert r.status_code == 409 and "maintenance" in r.json()["detail"]


def test_the_demo_customer_can_still_book(client, data):
    customer = keys(client, "customer")
    period = {"start_at": "2026-11-07T10:00", "end_at": "2026-11-07T15:00"}
    bikes = client.get("/api/availability", params={**period, "category": "ebike"}, headers=customer).json()["bikes"]
    assert bikes
    r = client.post("/api/rentals", json={"bike_id": bikes[0]["bike"]["id"], **period}, headers=customer)
    assert r.status_code == 200
