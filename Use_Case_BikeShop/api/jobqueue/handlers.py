"""
Job handlers, one per `kind` (SPEC §5.8).

A handler takes the job's payload (a dict) and returns its result (a dict
stored in `job_queue.result`, or None). If it raises, the worker records the
error and retries the job later.

Registered here: `send_email` (SPEC §5.9).

Registered elsewhere: `assistant_reply`, one answer of the website's AI
assistant, in `api/services/chat_service.py` (SPEC §13.8); `scripts/worker.py` imports
that module so the handler exists. A kind without a handler fails at once
with "No handler for job kind '…'".
"""
from typing import Callable, Optional

from ..mail import domain_of, make_mailer

Handler = Callable[[dict], Optional[dict]]

HANDLERS: dict[str, Handler] = {}


def register(kind: str):
    """Decorator: make `fn` the handler for jobs of this kind."""
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return wrap


@register("send_email")
def send_email(payload: dict) -> dict:
    """
    Payload: {"to", "subject", "text", "html"}. Addresses ending in `.test`
    (the seeded demo accounts, RFC 2606: never deliverable) are skipped.
    """
    to = payload["to"]
    if domain_of(to).endswith(".test"):
        return {"skipped": ".test address"}
    mailer = make_mailer()
    mailer.send(to=to, subject=payload["subject"], text=payload["text"], html=payload.get("html"))
    # The logging mailer delivers nothing: say so, so a production set-up
    # without a key doesn't look healthy (as kooistra-mailer's "skipped").
    return {"sent": mailer.name != "logging", "backend": mailer.name}
