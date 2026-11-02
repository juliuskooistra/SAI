"""
The scheduled job: release sale-bike reservations that ran out (SPEC §5.7).

Runs as its own process (the `scheduler` container in docker-compose.yml), not
inside the API: the API runs 4 uvicorn workers, so a loop in there would run 4
times. The job is safe to run twice anyway (conditional updates).

    python -m scripts.scheduler          # run forever, every EXPIRE_EVERY_MINUTES
    python -m scripts.scheduler --once   # run once and exit
"""
import argparse
import logging
import time

from sqlmodel import Session

from api.config import EXPIRE_EVERY_MINUTES
from api.database import engine, init_database
from api.models.models import JobRun
from api.services.order_service import OrderService
from api.timeutils import utcnow

JOB_NAME = "expire-reservations"
log = logging.getLogger("scheduler")


def record(ok: bool, result: str) -> None:
    """Write the run to JobRun, shown on /health and the staff board."""
    with Session(engine) as db:
        run = db.get(JobRun, JOB_NAME) or JobRun(name=JOB_NAME, last_run_at=utcnow(), last_ok=ok, last_result=result)
        run.last_run_at, run.last_ok, run.last_result = utcnow(), ok, result
        db.add(run)
        db.commit()


def run_once() -> int | None:
    """Expire due reservations. Returns how many, or None if the run failed."""
    try:
        with Session(engine) as db:
            expired = OrderService().expire_reservations(db)
    except Exception as e:  # noqa: BLE001 - a failing run is logged and the loop goes on
        log.exception("expire-reservations failed")
        record(False, f"{e.__class__.__name__}: {e}")
        return None
    result = f"expired {expired} orders"
    log.info(result)
    record(True, result)
    return expired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="run once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    init_database()
    if args.once:
        run_once()
        return
    log.info("scheduler started: expire-reservations every %d minutes", EXPIRE_EVERY_MINUTES)
    while True:
        run_once()  # also runs at start-up, so missed runs are made up after a restart
        time.sleep(EXPIRE_EVERY_MINUTES * 60)


if __name__ == "__main__":
    main()
