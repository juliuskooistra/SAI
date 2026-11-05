"""
Queue operations on the `job_queue` table (SPEC §5.8).

Adapted from AI Beacon's Postgres queue (`backend/jobqueue/queue.py`) for
SQLite and SQLModel:

- Postgres claims with `FOR UPDATE SKIP LOCKED`. SQLite has no row locks, so
  the claim runs in `BEGIN IMMEDIATE` (`start_write_transaction`): it holds
  the database's single write lock, and a second worker waits for it, then
  finds the job already taken.
- Times come from `utcnow()` (the worker's clock) instead of the database's
  `now()`: there is one machine, and tests can freeze it.

`enqueue` writes in the caller's transaction, so a booking and its email
commit together, or neither does. Every other function commits its own work:
give it a short-lived session of its own.

Fencing: every write about a claimed job matches (id, attempts, status =
'running'). If the job was requeued meanwhile (the reaper thought its worker
was dead), the write changes nothing and the function says so.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from sqlalchemy import String, and_, cast, func, literal, select, update
from sqlmodel import Session

from ..config import JOB_MAX_ATTEMPTS, JOB_MAX_ERROR_CHARS, JOB_RETRY_BASE_SECONDS
from ..database import start_write_transaction
from ..models.models import Job
from ..timeutils import utcnow

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
STATUSES = (QUEUED, RUNNING, DONE, FAILED)

T = Job.__table__   # the plain table: core UPDATEs, no ORM bookkeeping


@dataclass(frozen=True)
class Claimed:
    """One claimed attempt of a job. `attempt` is the fencing token."""
    id: int
    kind: str
    payload: dict = field(compare=False, hash=False)
    attempt: int = 0
    max_attempts: int = JOB_MAX_ATTEMPTS


def enqueue(db: Session, kind: str, payload: dict, *, user_id: Optional[str] = None,
            max_attempts: int = JOB_MAX_ATTEMPTS) -> Job:
    """Add a queued job to the caller's transaction. Doesn't commit."""
    job = Job(kind=kind, payload=payload, user_id=user_id, max_attempts=max_attempts)
    db.add(job)
    db.flush()   # gives the job its id; the caller's commit makes it visible
    return job


def claim(db: Session, worker_id: str, only: tuple = (), skip: tuple = ()) -> Optional[Claimed]:
    """
    Claim the oldest due queued job, or return None. Commits.
    `only` and `skip` limit it to some kinds of job (the worker's lanes, SPEC §14.10).
    """
    now = utcnow()
    due = and_(T.c.status == QUEUED, T.c.run_after <= now)
    if only:
        due = and_(due, T.c.kind.in_(only))
    if skip:
        due = and_(due, T.c.kind.not_in(skip))
    # A plain read first: an empty queue doesn't take the write lock every poll.
    if db.execute(select(T.c.id).where(due).limit(1)).first() is None:
        return None
    start_write_transaction(db)   # SQLite's stand-in for FOR UPDATE SKIP LOCKED
    oldest = select(T.c.id).where(due).order_by(T.c.run_after, T.c.id).limit(1).scalar_subquery()
    row = db.execute(
        update(T).where(T.c.id == oldest, T.c.status == QUEUED)
        .values(status=RUNNING, attempts=T.c.attempts + 1, worker_id=worker_id,
                heartbeat_at=now, started_at=now, finished_at=None)
        .returning(T.c.id, T.c.kind, T.c.payload, T.c.attempts, T.c.max_attempts)
    ).first()
    db.commit()
    if row is None:
        return None
    return Claimed(id=row.id, kind=row.kind, payload=row.payload or {},
                   attempt=row.attempts, max_attempts=row.max_attempts)


def _owned(job: Claimed):
    """The fencing condition: still this attempt, still running."""
    return and_(T.c.id == job.id, T.c.attempts == job.attempt, T.c.status == RUNNING)


def _fenced_update(db: Session, job: Claimed, **values) -> bool:
    start_write_transaction(db)
    changed = db.execute(update(T).where(_owned(job)).values(**values)).rowcount == 1
    db.commit()
    return changed


def heartbeat(db: Session, job: Claimed) -> bool:
    """Stamp heartbeat_at. False if the job is no longer ours. Commits."""
    return _fenced_update(db, job, heartbeat_at=utcnow())


def finish(db: Session, job: Claimed, result: Optional[dict]) -> bool:
    """Mark the attempt done with its result. False if no longer ours. Commits."""
    return _fenced_update(db, job, status=DONE, result=result, error=None, finished_at=utcnow())


def fail(db: Session, job: Claimed, error: str, *, retry: bool = True) -> Optional[str]:
    """
    Record a failed attempt. With attempts left (and retry=True) the job goes
    back to the queue with run_after = now + 30 s x attempts; otherwise it is
    `failed`. Returns the new status, or None if the job was no longer ours.
    """
    now = utcnow()
    error = error[:JOB_MAX_ERROR_CHARS]
    if retry and job.attempt < job.max_attempts:
        changed = _fenced_update(
            db, job, status=QUEUED, error=error, worker_id=None, heartbeat_at=None,
            run_after=now + timedelta(seconds=JOB_RETRY_BASE_SECONDS * job.attempt))
        return QUEUED if changed else None
    changed = _fenced_update(db, job, status=FAILED, error=error, finished_at=now)
    return FAILED if changed else None


def reap(db: Session, stale_after: timedelta) -> tuple[list[int], list[int]]:
    """
    Running jobs whose heartbeat is older than `stale_after` (their worker
    died): back to the queue with attempts left, else `failed`. Commits.
    Returns (requeued ids, failed ids).
    """
    start_write_transaction(db)
    now = utcnow()
    stale = and_(T.c.status == RUNNING, T.c.heartbeat_at < now - stale_after)
    requeued = db.execute(
        update(T).where(stale, T.c.attempts < T.c.max_attempts)
        .values(status=QUEUED, worker_id=None, heartbeat_at=None, run_after=now,
                error=literal("The worker stopped while running attempt ") + cast(T.c.attempts, String)
                      + "; requeued.")
        .returning(T.c.id)
    ).scalars().all()
    failed = db.execute(
        update(T).where(stale, T.c.attempts >= T.c.max_attempts)
        .values(status=FAILED, finished_at=now,
                error=literal("The worker stopped while running this job; gave up after ")
                      + cast(T.c.attempts, String) + " attempts.")
        .returning(T.c.id)
    ).scalars().all()
    db.commit()
    return list(requeued), list(failed)


def counts(db: Session) -> dict[str, int]:
    """Number of jobs per status, every status present (for /health)."""
    rows = db.execute(select(T.c.status, func.count()).group_by(T.c.status)).all()
    found = {status: n for status, n in rows}
    return {status: found.get(status, 0) for status in STATUSES}


def get_job(db: Session, job_id: int) -> Optional[Job]:
    return db.get(Job, job_id)


def list_jobs(db: Session, status: Optional[str] = None, kind: Optional[str] = None,
              limit: int = 100) -> list[Job]:
    """Recent jobs, newest first."""
    query = select(Job)
    if status:
        query = query.where(Job.status == status)
    if kind:
        query = query.where(Job.kind == kind)
    return list(db.scalars(query.order_by(Job.enqueued_at.desc(), Job.id.desc()).limit(limit)).all())
