"""
One turn of the assistant's chat (SPEC §13.3, §13.8), used by the terminal
script and by the website.

  1. Send the conversation + tool menu to the AI.
  2. If the AI asks for tools: run them, send the results back, go to 1.
  3. If the AI answers with text: that's the answer.

The website runs a turn as a background job (`assistant_reply`): the API
enqueues it, the worker runs `assistant_reply()` below, and the page polls
GET /api/jobs/{id} for the result. No AI call ever runs inside a request.
"""
import json
import logging

from sqlmodel import Session, select

from .. import config
from ..database import engine
from ..jobqueue import queue
from ..jobqueue.handlers import register
from ..models.models import User
from .assistant_tools import TOOLS, run_tool, system_prompt
from .llm import AIError, Reply, connect

log = logging.getLogger("bikeshop.assistant")

MAX_TOOL_ROUNDS = 6   # an AI that keeps asking for tools is stopped (SPEC §13.8, layer 4)
TOO_MANY_ROUNDS = "Sorry, I couldn't finish that. Could you ask again, one thing at a time?"

# At most one of these per customer message (SPEC §13.8, layer 4): an injected
# "book every bike" or "email staff 100 times" stops at one.
ONCE_PER_MESSAGE = {
    "book_rental": "Only one booking per message. Tell the customer this one is not booked yet, "
                   "and ask them to confirm it in their next message.",
    "escalate_to_staff": "The request was already forwarded to staff in this message.",
}


def web_tools() -> list:
    """The website's menu: all five tools, without the hand-off if no staff address is set."""
    return [t for t in TOOLS if t["name"] != "escalate_to_staff" or config.SHOP_STAFF_EMAIL]


def escalate_by_email(db: Session, user_id: str, reason: str, customer_message: str) -> dict:
    """
    The website's escalate_to_staff: email the shop's staff (a send_email job,
    SPEC §5.9) so a person answers. Who the customer is comes from our database,
    never from the AI, and goes only into the email, not back to the AI.
    """
    user = db.exec(select(User).where(User.user_id == user_id)).first()
    reason = " ".join(str(reason).split())[:80]   # one line: it goes into the subject
    text = (f"A customer asked the BikeShop assistant to speak to a person.\n\n"
            f"Reason: {reason}\n"
            f"Customer: {user.username} <{user.email}>\n\n"
            f"Their message:\n{customer_message}\n\n"
            f"Please answer them by email within one working day.")
    job = queue.enqueue(db, "send_email", {"to": config.SHOP_STAFF_EMAIL,
                                           "subject": f"Assistant hand-off: {reason}", "text": text})
    db.commit()
    return {"status": "forwarded to staff", "ticket_id": f"T-{job.id}",
            "promise_to_customer": "A staff member will answer by email within one working day."}


def chat_turn(ai, messages: list, db: Session, user_id: str, show=print,
              run=run_tool, used: list | None = None, max_rounds: int = MAX_TOOL_ROUNDS) -> str:
    """One customer message -> tools as often as the AI asks -> the answer.
    `messages` is the whole conversation; the AI has no memory, we resend it each time.
    `run` runs one tool (the website passes a stricter one); `used` collects tool names."""
    try:
        reply = ai.ask(messages)

        # As long as the AI asks for tools, run them and send the results back.
        rounds = 0
        while reply.tool_calls:
            if rounds == max_rounds:   # don't let it loop forever
                reply = Reply(text=TOO_MANY_ROUNDS)
                break
            rounds += 1
            messages += ai.assistant_message(reply)

            results = []
            for call in reply.tool_calls:
                show(f"   [TOOL CALL] {call.name}({json.dumps(call.input)})")
                result = run(call.name, call.input, db, user_id)   # <- OUR code runs here
                show(f"   [RESULT]    {json.dumps(result, default=str)}")
                results.append(result)
                if used is not None:
                    used.append(call.name)

            messages += ai.tool_result_messages(reply.tool_calls, results)  # matched by id
            reply = ai.ask(messages)
    except AIError as e:  # busy, unreachable, wrong key: keep the conversation, try again
        return str(e)

    # The AI is done with tools: its answer.
    messages += ai.assistant_message(reply)
    return reply.text


def web_tool_runner():
    """run_tool for the website (SPEC §13.8): only the website's menu, the hand-off
    by email, and at most one booking and one hand-off per message."""
    allowed = {t["name"] for t in web_tools()}
    done = set()   # tools from ONCE_PER_MESSAGE that already succeeded in this message

    def run(name: str, inputs: dict, db: Session, user_id: str) -> dict:
        if name not in allowed:
            return {"error": f"Unknown tool '{name}'."}
        if name in done:
            return {"error": ONCE_PER_MESSAGE[name]}
        if name == "escalate_to_staff":
            try:
                result = escalate_by_email(db, user_id, **inputs)
            except TypeError as e:   # wrong or missing inputs, as in run_tool
                return {"error": f"Wrong input for {name}: {e}"}
        else:
            result = run_tool(name, inputs, db, user_id)
        if name in ONCE_PER_MESSAGE and "error" not in result:
            done.add(name)
        return result

    return run


@register("assistant_reply")
def assistant_reply(payload: dict) -> dict:
    """
    The worker's handler for one website chat turn. Payload:
    {"messages": [{"role": "user"|"assistant", "content": "..."}], "user_id": "..."}.
    Result: {"text": the answer, "tools": names of the tools it used}.
    """
    try:
        ai = connect(system_prompt(), web_tools(), provider="bfh")   # the website always uses BFH
    except SystemExit as e:   # connect() exits for the terminal; that would stop the worker
        raise RuntimeError(str(e)) from None
    used: list[str] = []
    with Session(engine) as db:
        text = chat_turn(ai, list(payload["messages"]), db, payload["user_id"],
                         show=lambda line: None, run=web_tool_runner(), used=used)
    log.info("assistant answered", extra={"tools": used})   # tool names only, never the text
    return {"text": text, "tools": used}
