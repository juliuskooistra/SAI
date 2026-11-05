"""
The Workshop agent's loop (SPEC §14.1, §14.10): one model round per job.

The website's assistant runs a whole turn in one job. This agent thinks for
longer, so each ROUND is its own `workshop_step` job:

  1. Check the budget (BFH's limits are shared with the assistant).
  2. Rebuild the conversation from the database and ask the model once.
  3. Run the tools it asks for and save everything.
  4. Handed-in result: the stage moves on. Otherwise: queue the next round.

Because the queue is first come, first served, a customer's chat answer fits in
between two rounds. And because everything is in the database, nothing is lost
if the app restarts or scales to zero: the next job just carries on.
"""
import json
import logging
from datetime import timedelta

from sqlmodel import Session, select

from .. import config
from ..database import engine
from ..jobqueue import queue
from ..jobqueue.handlers import register
from ..models.models import WorkshopCase, WorkshopEvent
from ..timeutils import utcnow
from ..tools import workshop_tools as tools
from . import guard_service, llm_service, scan_service, workshop_service as shop
from .llm_service import AIError, Busy, NotConfigured, Reply, ToolCall

log = logging.getLogger("bikeshop.workshop")

WAITING_NOTE = "Waiting for AI capacity"
GUESS_TOKENS = 8000      # a round's size, before we have seen one


def budget_wait(db: Session, case: WorkshopCase) -> int:
    """Seconds to wait before the next round may start; 0 means go (SPEC §14.10)."""
    now = utcnow()
    recent = db.exec(select(WorkshopEvent).where(WorkshopEvent.kind == "round",
                                                 WorkshopEvent.created_at >= now - timedelta(seconds=60))
                     .order_by(WorkshopEvent.created_at)).all()
    tokens = sum(e.tokens for e in recent)
    guess = max((e.tokens for e in recent if e.case_id == case.id), default=GUESS_TOKENS)
    if len(recent) < config.WORKSHOP_REQUESTS_PER_MINUTE and tokens + guess <= config.WORKSHOP_TOKENS_PER_MINUTE:
        return 0
    oldest = recent[0].created_at
    return max(1, 60 - int((now - oldest.replace(tzinfo=now.tzinfo)).total_seconds()))


def _facts(db: Session, case: WorkshopCase) -> str:
    """What the agent knows at the start of each stage: never the whole scan (SPEC §14.10)."""
    facts = {"case": case.id, "stage": case.stage}
    if case.brief:
        scan = shop.case_scan(db, case)
        facts["scan_findings"] = [{k: r[k] for k in ("name", "value", "unit", "watch", "unfit", "status", "part")}
                                  for r in scan_service.findings(scan.readings)]
        facts["bookings"] = [{"rental_id": r.id, "start_at": str(r.start_at), "price_chf": str(r.quoted_price_chf)}
                             for r in shop.upcoming_bookings(db, case.bike_id)][:8]
        facts["brief_you_wrote"] = {k: case.brief[k] for k in ("verdict", "verdict_sentence", "what_is_wrong", "recommended", "recommended_why")}
        facts["options"] = [{k: c[k] for k in ("key", "kind", "title", "what_we_do", "cost_chf", "ready_date", "bookings_affected", "parts")}
                            for c in case.brief["options"]]
    if case.chosen_option:
        facts["staff_chose"] = case.chosen_option
    if case.agent_agreed is not None:
        facts["you_agreed_with_the_choice"] = case.agent_agreed
    if case.plan:
        facts["current_plan"] = case.plan
    return json.dumps(facts, default=str)


def build_messages(db: Session, case: WorkshopCase, ai) -> list:
    """Rebuild the conversation: the facts, the last messages, then this turn's rounds and tool results."""
    events = shop.events_of(db, case.id)
    stage_events = [e for e in events if e.stage == case.stage]
    talk = [e for e in stage_events if e.kind in ("message", "position", "choice")]
    messages = [{"role": "user", "content": _facts(db, case)}]
    for e in talk[-config.WORKSHOP_HISTORY_MESSAGES:]:
        messages.append({"role": "user" if e.author == "staff" else "assistant", "content": e.content})
    last_talk = talk[-1].id if talk else 0
    for e in stage_events:
        if e.id <= last_talk:
            continue
        if e.kind == "round":
            calls = [ToolCall(c["id"], c["name"], c["input"]) for c in (e.data or {}).get("tool_calls", [])]
            messages += ai.assistant_message(Reply(text=e.content, tool_calls=calls))
        elif e.kind == "tool":
            call = ToolCall(e.data["call_id"], e.data["name"], {})
            messages += ai.tool_result_messages([call], [e.data["result"]])
        elif e.kind == "reminder":
            messages.append({"role": "user", "content": e.content})
    return messages


def _rounds_this_turn(events: list, stage: str) -> int:
    rounds = 0
    for e in reversed(events):
        if e.stage != stage or e.kind in ("message", "choice", "retry"):
            break
        rounds += e.kind == "round"
    return rounds


def _run_calls(db: Session, case: WorkshopCase, calls: list) -> bool:
    """Run what the model asked for. True if a handed-in result ended this turn."""
    finished = False
    for call in calls:
        if call.name == "submit_brief":
            result = shop.submit_brief(db, case, call.input)
        elif call.name == "submit_plan":
            result = shop.submit_plan(db, case, call.input)
        elif call.name == "submit_position":
            result = _position(db, case, call.input)
        else:
            result = tools.capped(tools.run_tool(call.name, call.input, db, case))
        shop.log(db, case, "code", "tool", call.name,
                 data={"call_id": call.id, "name": call.name, "result": result})
        finished = finished or (call.name.startswith("submit_") and "error" not in result)
    return finished


def _position(db: Session, case: WorkshopCase, answer: dict) -> dict:
    """The agent's answer in a discussion. Its disagreement is kept on record (SPEC §14.1)."""
    text = str(answer.get("message", "")).strip()
    if not text:
        return {"error": "message is empty."}
    if shop.doubts_the_scan(text):
        return {"error": shop.TRUST_THE_SCAN}
    case.agent_agreed = bool(answer.get("agrees"))
    case.agent_state = "idle"
    shop.log(db, case, "agent", "position", text,
             data={"agrees": case.agent_agreed, "prefers": answer.get("safer_or_better_option")})
    db.add(case)
    return {"ok": True}


def _next_round(db: Session, case: WorkshopCase, delay: int = 0, retries: int = 0) -> None:
    case.step_no += 1
    db.add(case)
    job = queue.enqueue(db, "workshop_step", {"case_id": case.id, "step_no": case.step_no, "retries": retries},
                        max_attempts=1)
    if delay:
        job.run_after = utcnow() + timedelta(seconds=delay)
        db.add(job)


def _stop(db: Session, case: WorkshopCase, note: str) -> None:
    """Give up for now: staff see the reason and a Retry button."""
    case.agent_state, case.agent_note = "failed", note
    db.add(case)
    shop.log(db, case, "code", "note", note)


def connect_agent(stage: str):
    """The model for one stage. A person may be waiting, so each call has hard limits:
    a time limit, a length limit, and no silent retries by the library (we retry ourselves)."""
    ai = llm_service.connect(tools.workshop_prompt(stage), tools.tools_for(stage),
                             provider="bfh", model=config.WORKSHOP_MODEL)
    ai.client = ai.client.with_options(timeout=config.WORKSHOP_CALL_TIMEOUT_SECONDS, max_retries=0)
    ai.max_tokens = config.WORKSHOP_CHAT_REPLY_TOKENS if stage == shop.DISCUSSING else config.WORKSHOP_MAX_REPLY_TOKENS
    return ai


def one_round(db: Session, case: WorkshopCase, ai=None) -> None:
    """One model call and its tools. Everything it learns is saved before the next round."""
    step = case.step_no
    wait = budget_wait(db, case)
    if wait:
        case.agent_state, case.agent_note = "waiting", WAITING_NOTE
        _next_round(db, case, delay=wait)
        return
    case.agent_state, case.agent_note = "working", None
    db.add(case)
    db.commit()     # never hold SQLite's write lock during a model call: it can take minutes
    events = shop.events_of(db, case.id)
    limit = config.WORKSHOP_CHAT_ROUNDS if case.stage == shop.DISCUSSING else config.WORKSHOP_MAX_ROUNDS
    if _rounds_this_turn(events, case.stage) >= limit:
        _stop(db, case, f"The agent didn't finish within {limit} rounds. Press Retry.")
        return
    ai = ai or connect_agent(case.stage)
    reply = ai.ask(build_messages(db, case, ai))
    db.refresh(case)
    if case.step_no != step:
        return      # staff wrote or chose something meanwhile: that newer step answers instead
    shop.log(db, case, "agent", "round", reply.text, reasoning=reply.reasoning or None, tokens=reply.tokens,
             data={"tool_calls": [{"id": c.id, "name": c.name, "input": c.input} for c in reply.tool_calls]})
    if reply.tool_calls:
        finished = _run_calls(db, case, reply.tool_calls)
    elif case.stage == shop.DISCUSSING and shop.doubts_the_scan(reply.text):
        shop.log(db, case, "code", "reminder", shop.TRUST_THE_SCAN)
        finished = False
    elif case.stage in (shop.DISCUSSING, shop.PLAN_REVIEW) and reply.text.strip():
        shop.log(db, case, "agent", "message", reply.text)     # a plain answer in a conversation is fine
        case.agent_state = "idle"
        finished = True
    else:
        shop.log(db, case, "code", "reminder", "Hand in your result with the submit tool.")
        finished = False
    if not finished:
        _next_round(db, case)
    db.add(case)


def _screen_staff_message(db: Session, case: WorkshopCase) -> None:
    """Log known injection phrasings. Staff are never blocked by a false alarm (SPEC §14.5)."""
    last = [e for e in shop.events_of(db, case.id) if e.author == "staff" and e.kind == "message"]
    if last:
        hits = guard_service.PromptGuard.scan(last[-1].content).patterns
        if hits:
            log.warning("workshop message matched the prompt guard", extra={"patterns": hits})


@register("workshop_step")
def workshop_step(payload: dict) -> dict:
    """One round. Payload: {"case_id", "step_no", "retries"}. It never raises: a problem is shown on the case."""
    with Session(engine) as db:
        case = db.get(WorkshopCase, payload["case_id"])
        if case is None or case.step_no != payload["step_no"] or case.stage not in shop.AGENT_STAGES:
            return {"skipped": "an older step"}     # a repeated job finds nothing to do
        stage = case.stage
        _screen_staff_message(db, case)
        try:
            one_round(db, case)
            db.commit()
        except Busy:
            db.rollback()
            case = db.get(WorkshopCase, payload["case_id"])
            if case.step_no != payload["step_no"]:
                return {"skipped": "a newer step"}
            case.agent_state, case.agent_note = "waiting", WAITING_NOTE
            _next_round(db, case, delay=config.WORKSHOP_RETRY_SECONDS, retries=payload["retries"])
            db.commit()
        except NotConfigured as e:
            db.rollback()
            _stop(db, db.get(WorkshopCase, payload["case_id"]), str(e))
            db.commit()
        except Exception as e:  # noqa: BLE001 - shown on the case, and the worker carries on
            db.rollback()
            case = db.get(WorkshopCase, payload["case_id"])
            log.exception("workshop round failed", extra={"case_id": case.id})
            if case.step_no != payload["step_no"]:
                return {"skipped": "a newer step"}
            if payload["retries"] + 1 < config.WORKSHOP_RETRIES:
                case.agent_state, case.agent_note = "waiting", "The AI didn't answer in time. Trying again"
                _next_round(db, case, delay=config.WORKSHOP_RETRY_SECONDS, retries=payload["retries"] + 1)
            else:
                _stop(db, case, str(e) if isinstance(e, AIError) else "The AI answer couldn't be used. Press Retry.")
            db.commit()
        return {"stage": stage}
