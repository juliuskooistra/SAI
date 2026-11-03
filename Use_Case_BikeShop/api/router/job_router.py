from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field as PField
from sqlmodel import Session

from ..database import get_db
from ..jobqueue import queue
from ..models.models import LocalTimes
from ..services.errors import NotFound


class JobResponse(LocalTimes):
    """A background job (SPEC §5.8). The payload is left out: it can hold email addresses."""
    id: int
    kind: str = PField(description="What the job does", examples=["send_email"])
    status: str = PField(description="queued | running | done | failed", examples=["done"])
    attempts: int = PField(description="Attempts started so far")
    max_attempts: int
    user_id: Optional[str] = PField(default=None, description="Owner; null for system jobs")
    enqueued_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[dict] = PField(default=None, description="The handler's output once done",
                                    examples=[{"sent": True, "backend": "mailgun"}])
    error: Optional[str] = PField(default=None, description="The last error, if an attempt failed")


JobStatusFilter = Literal["queued", "running", "done", "failed"]


class JobRouter:
    """
    Background jobs. `.router` (mounted at /api) shows a customer one of their
    own jobs; `.staff_router` (mounted at /staff) lists recent jobs.
    Authentication and the staff role are checked by middleware.
    """

    def __init__(self):
        self.router = APIRouter()
        self.staff_router = APIRouter()
        self._register_routes()

    def _register_routes(self):
        """The function names are the operation_ids (SPEC §6, §8)."""
        self.router.get("/jobs/{job_id}", response_model=JobResponse,
                        summary="Status and result of one of your background jobs")(self.get_my_job)
        self.staff_router.get("/jobs", response_model=List[JobResponse],
                              summary="Recent background jobs, newest first")(self.list_jobs)

    def get_my_job(self, job_id: int, req: Request, db: Session = Depends(get_db)) -> JobResponse:
        """
        Use this to poll a slow task you started (e.g. an LLM answer): its
        status, attempts, result and error. Only your own jobs (else 404).
        """
        job = queue.get_job(db, job_id)
        if job is None or job.user_id != req.state.user_id:
            raise NotFound(f"There is no job with id {job_id} on your account.")
        return JobResponse.model_validate(job)

    def list_jobs(self,
                  status: Optional[JobStatusFilter] = Query(None, description="Only jobs in this status"),
                  kind: Optional[str] = Query(None, description="Only jobs of this kind", examples=["send_email"]),
                  db: Session = Depends(get_db)) -> List[JobResponse]:
        """Recent background jobs (at most 100), newest first, e.g. to spot failed emails."""
        return [JobResponse.model_validate(j) for j in queue.list_jobs(db, status, kind, limit=100)]
