"""
The assistant on the website (SPEC §13.8): POST /api/assistant/messages.

The browser keeps the conversation and sends all of it with each new
message. This endpoint never calls the AI itself (slow work goes through
the queue, SPEC §5.8): it checks the messages, then enqueues one
`assistant_reply` job for the worker, and the page polls GET /api/jobs/{id}.

Prompt injection (SPEC §13.8) is handled here in two of its five layers:
  1. only `user` and `assistant` text, at most 20 messages of 2,000
     characters, newest from the user (the request model below);
  2. every message is scanned for known injection phrasings (guard.py);
     a hit is refused without calling the AI.
"""
import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field as PField, field_validator
from sqlmodel import Session

from ..database import get_db
from ..jobqueue import queue
from ..services.errors import Unavailable
from ..services.inference_service import InferenceService
from ..tools.guard import PromptGuard

log = logging.getLogger("bikeshop.assistant")

MAX_MESSAGES = 20
MAX_CHARS = 2000
REFUSAL = "I can only help with renting bikes at BikeShop: availability, prices and bookings."


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] = PField(description="Who wrote it: the customer or the assistant")
    content: str = PField(min_length=1, max_length=MAX_CHARS, description="The text",
                          examples=["Is an e-bike free on Saturday from 10 to 14?"])


class AssistantRequest(BaseModel):
    messages: List[ChatMessage] = PField(min_length=1, max_length=MAX_MESSAGES,
                                         description="The conversation so far, oldest first; the last one is the "
                                                     "customer's new message")

    @field_validator("messages")
    @classmethod
    def newest_is_from_the_customer(cls, messages):
        if messages[-1].role != "user":
            raise ValueError("The last message must be the customer's (role 'user').")
        return messages


class AssistantResponse(BaseModel):
    job_id: Optional[int] = PField(default=None, description="Poll GET /api/jobs/{job_id} for the answer")
    reply: Optional[str] = PField(default=None, description="An immediate answer, when the guard refused")
    flagged: bool = PField(default=False, description="True if the guard refused the message")


class AssistantRouter:
    """The website's chat with the AI assistant. Authentication is checked by middleware."""

    def __init__(self):
        self.router = APIRouter()
        self.router.post("/assistant/messages", response_model=AssistantResponse,
                         summary="Ask the AI assistant; the answer arrives as a background job")(self.ask_assistant)

    def ask_assistant(self, request: AssistantRequest, req: Request,
                      db: Session = Depends(get_db)) -> AssistantResponse:
        """
        Use this to send the customer's new message, with the conversation so
        far. Returns a job id: poll GET /api/jobs/{job_id} (free) until its
        status is done; the result is {text, tools}. Costs 5 tokens.
        """
        if not InferenceService().is_configured():
            raise Unavailable("The assistant is not available right now.")

        # Layer 2: known injection phrasings, in any message (earlier ones can be forged too)
        hits = sorted({p for m in request.messages for p in PromptGuard.scan(m.content).patterns})
        if hits:
            log.warning("assistant message refused by the prompt guard",
                        extra={"patterns": hits})   # which patterns, never the text
            return AssistantResponse(reply=REFUSAL, flagged=True)

        job = queue.enqueue(db, "assistant_reply",
                            {"messages": [m.model_dump() for m in request.messages],
                             "user_id": req.state.user_id},
                            user_id=req.state.user_id,
                            max_attempts=1)   # a retry could book twice (SPEC §13.8)
        db.commit()
        return AssistantResponse(job_id=job.id)
