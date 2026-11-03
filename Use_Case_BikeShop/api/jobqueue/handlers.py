"""
Job handlers, one per `kind` (SPEC §5.8).

A handler takes the job's payload (a dict) and returns its result (a dict
stored in `job_queue.result`, or None). If it raises, the worker records the
error and retries the job later.

Registered here: `send_email` (SPEC §5.9).

Deliberately not registered: `llm_task`. That kind is reserved for the
colleague's LLM tools (SPEC §8.2 point 7): they add a handler with
`@register("llm_task")` in `api/tools/` and import that module in
`scripts/worker.py`. Until then, `llm_task` jobs fail at once with
"No handler for job kind 'llm_task'".
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
