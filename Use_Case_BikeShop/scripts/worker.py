"""
The worker: runs background jobs from the queue and the scheduled jobs
(SPEC §5.7, §5.8, §5.10).

Its own process (the `worker` container in docker-compose.yml), not inside
the API: the API runs 4 uvicorn workers, so a loop in there would run 4
times. Every cycle it

1. notes that it is alive (JobRun "worker", for /health; at most every 30 s),
2. requeues jobs whose worker died (stale heartbeat),
3. runs the reservation expiry every EXPIRE_EVERY_MINUTES (and at start-up),
4. deletes analytics events older than ANALYTICS_KEEP_DAYS (once a day),
5. claims and runs queued jobs, one at a time, heart-beating while each runs.

Adapted from AI Beacon's `backend/jobqueue/worker.py`: that one is asyncio
with several jobs at once; this one is a plain loop with one job at a time,
which also keeps MLMP's limit of 2 concurrent requests (SPEC §8.2).

    python -m scripts.worker          # run forever, polling every WORKER_POLL_SECONDS
    python -m scripts.worker --once   # one cycle (all due work), then exit
"""
import argparse
import logging
import os
import socket
import threading
import time
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete
from sqlmodel import Session

from api.config import (
    ANALYTICS_KEEP_DAYS, EXPIRE_EVERY_MINUTES, JOB_HEARTBEAT_SECONDS, JOB_STALE_AFTER_SECONDS,
    WORKER_POLL_SECONDS,
)
from api.database import engine, init_database, start_write_transaction
from api.jobqueue import queue
from api.jobqueue.handlers import HANDLERS
import api.services.chat_service  # noqa: F401  registers the assistant_reply handler (SPEC §13.8)
from api.models.models import AnalyticsEvent, JobRun
from api.observability import setup_logging
from api.services.order_service import OrderService
from api.timeutils import to_local, utcnow

EXPIRE_JOB = "expire-reservations"
CLEANUP_JOB = "analytics-cleanup"
WORKER_ROW = "worker"
SEEN_EVERY_SECONDS = 30
MAX_JOBS_PER_CYCLE = 50   # so a flood of jobs can't hold up the scheduled ones for long

log = logging.getLogger("worker")


def record(name: str, ok: bool, result: str) -> None:
    """Write a run to JobRun (shown on /health and the staff board)."""
    with Session(engine) as db:
        start_write_transaction(db)
        run = db.get(JobRun, name) or JobRun(name=name, last_run_at=utcnow(), last_ok=ok, last_result=result)
        run.last_run_at, run.last_ok, run.last_result = utcnow(), ok, result
        db.add(run)
        db.commit()


# ---------------------------------------------------------------- scheduled jobs

def run_expiry() -> Optional[int]:
    """Expire due reservations (SPEC §5.7). Returns how many, or None if the run failed."""
    try:
        with Session(engine) as db:
            expired = OrderService().expire_reservations(db)
    except Exception as e:  # noqa: BLE001 - a failing run is logged and the loop goes on
        log.exception("expire-reservations failed")
        record(EXPIRE_JOB, False, f"{e.__class__.__name__}: {e}")
        return None
    result = f"expired {expired} orders"
    log.info(result, extra={"job": EXPIRE_JOB})
    record(EXPIRE_JOB, True, result)
    return expired


def run_analytics_cleanup() -> Optional[int]:
    """Delete analytics events older than ANALYTICS_KEEP_DAYS (SPEC §5.10)."""
    try:
        cutoff = to_local(utcnow()).date() - timedelta(days=ANALYTICS_KEEP_DAYS)
        with Session(engine) as db:
            start_write_transaction(db)
            deleted = db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.day < cutoff)).rowcount
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("analytics-cleanup failed")
        record(CLEANUP_JOB, False, f"{e.__class__.__name__}: {e}")
        return None
    result = f"deleted {deleted} events"
    log.info(result, extra={"job": CLEANUP_JOB})
    record(CLEANUP_JOB, True, result)
    return deleted


# ---------------------------------------------------------------- queued jobs

class _Heartbeat:
    """Refreshes a running job's heartbeat_at every JOB_HEARTBEAT_SECONDS, in a thread."""

    def __init__(self, job: queue.Claimed, every: float = JOB_HEARTBEAT_SECONDS):
        self.job, self.every = job, every
        self.lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{job.id}", daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()

    def _run(self):
        while not self._stop.wait(self.every):
            try:
                with Session(engine) as db:
                    if not queue.heartbeat(db, self.job):
                        # Requeued under us. A synchronous handler can't be
                        # interrupted; fencing makes its outcome a no-op.
                        self.lost = True
                        log.warning("job %s is no longer ours (requeued)", self.job.id)
                        return
            except Exception:  # noqa: BLE001
                log.exception("heartbeat for job %s failed", self.job.id)


def run_job(job: queue.Claimed) -> str:
    """Run one claimed job and record the outcome. Returns done | retry | failed | lost."""
    started = time.perf_counter()
    handler = HANDLERS.get(job.kind)
    error, result, retry = None, None, True
    if handler is None:
        error, retry = f"No handler for job kind '{job.kind}'", False   # fails at once (SPEC §5.8)
    else:
        try:
            with _Heartbeat(job):
                result = handler(job.payload)
        except Exception as e:  # noqa: BLE001 - recorded on the job, retried
            error = f"{e.__class__.__name__}: {e}"

    with Session(engine) as db:
        if error is None:
            outcome = "done" if queue.finish(db, job, result) else "lost"
        else:
            status = queue.fail(db, job, error, retry=retry)
            outcome = {queue.QUEUED: "retry", queue.FAILED: "failed", None: "lost"}[status]

    fields = {"job_id": job.id, "kind": job.kind, "attempt": job.attempt, "outcome": outcome,
              "duration_ms": round((time.perf_counter() - started) * 1000)}
    if outcome == "done":
        log.info("job %s (%s) done", job.id, job.kind, extra=fields)
    elif outcome == "lost":
        log.warning("job %s (%s) finished after it was requeued; outcome dropped", job.id, job.kind, extra=fields)
    else:
        log.error("job %s (%s) attempt %d failed: %s", job.id, job.kind, job.attempt, error,
                  extra={**fields, "error": error})
    return outcome


# ---------------------------------------------------------------- the loop

class Worker:
    """State between cycles: when each scheduled job is due next."""

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.next_expiry_at = None      # None: due now (at start-up)
        self.last_cleanup_day = None
        self._last_seen_write = None    # time.monotonic() of the last "worker" JobRun write

    def mark_seen(self) -> None:
        """JobRun 'worker' = when the worker last polled (at most every 30 s)."""
        now = time.monotonic()
        if self._last_seen_write is not None and now - self._last_seen_write < SEEN_EVERY_SECONDS:
            return
        record(WORKER_ROW, True, f"polling as {self.worker_id}")
        self._last_seen_write = now

    def reap(self) -> None:
        with Session(engine) as db:
            requeued, failed = queue.reap(db, timedelta(seconds=JOB_STALE_AFTER_SECONDS))
        for job_id in requeued:
            log.warning("job %s had a stale heartbeat; requeued", job_id, extra={"job_id": job_id})
        for job_id in failed:
            log.error("job %s had a stale heartbeat and no attempts left; failed", job_id,
                      extra={"job_id": job_id, "outcome": "failed"})

    def run_scheduled(self) -> None:
        now = utcnow()
        if self.next_expiry_at is None or now >= self.next_expiry_at:
            run_expiry()
            self.next_expiry_at = now + timedelta(minutes=EXPIRE_EVERY_MINUTES)
        today = to_local(now).date()
        if self.last_cleanup_day != today:
            run_analytics_cleanup()
            self.last_cleanup_day = today

    def run_jobs(self, limit: int = MAX_JOBS_PER_CYCLE) -> int:
        """Claim and run due jobs until the queue is empty (or `limit`). Returns how many ran."""
        ran = 0
        while ran < limit:
            with Session(engine) as db:
                job = queue.claim(db, self.worker_id)
            if job is None:
                break
            run_job(job)
            ran += 1
        return ran

    def run_cycle(self) -> int:
        """One pass: alive, reap, scheduled jobs, queued jobs. Each step's failure is logged, not fatal."""
        ran = 0
        for step in (self.mark_seen, self.reap, self.run_scheduled):
            try:
                step()
            except Exception:  # noqa: BLE001 - the loop must keep going
                log.exception("worker step %s failed", step.__name__)
        try:
            ran = self.run_jobs()
        except Exception:  # noqa: BLE001
            log.exception("running queued jobs failed")
        return ran

    def run_forever(self) -> None:
        log.info("worker %s started: polling every %ss, expire-reservations every %d minutes, kinds %s",
                 self.worker_id, WORKER_POLL_SECONDS, EXPIRE_EVERY_MINUTES, sorted(HANDLERS))
        while True:
            if self.run_cycle() == 0:   # busy: go straight on; idle: wait
                time.sleep(WORKER_POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = parser.parse_args()
    setup_logging(service="bikeshop-worker")
    init_database()
    worker = Worker()
    if args.once:
        worker.run_cycle()
        return
    worker.run_forever()


if __name__ == "__main__":
    main()
