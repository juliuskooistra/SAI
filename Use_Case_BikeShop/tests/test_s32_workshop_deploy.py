"""
S32: deploying the Workshop (SPEC §14.10, §14.13).

Two things that only show up on a real deployment: a long Workshop round must
not hold up a customer's assistant answer, and the new release must work on a
database made by the previous one.
"""
import threading
from datetime import timedelta

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel

from api import timeutils
from api.database import engine, init_database
from api.jobqueue import queue
from api.jobqueue.handlers import HANDLERS
from api.models.models import Job
from scripts import seed, seed_history, seed_workshop, worker
from tests.conftest import NOW

WORKSHOP_TABLES = ("workshopscan", "workshopcase", "workshopevent", "supplier", "partoffer",
                   "bikefinance", "customeraction")


def add_job(kind: str) -> int:
    with Session(engine) as db:
        job = queue.enqueue(db, kind, {})
        db.commit()
        return job.id


def status(job_id: int) -> str:
    with Session(engine) as db:
        return db.get(Job, job_id).status


@pytest.fixture
def handlers(monkeypatch):
    """Handlers that only record that they ran, so no job needs a model."""
    ran = []
    monkeypatch.setitem(HANDLERS, "workshop_step", lambda payload: ran.append("workshop_step"))
    monkeypatch.setitem(HANDLERS, "assistant_reply", lambda payload: ran.append("assistant_reply"))
    return ran


# ---------------------------------------------------------------- the lanes

def test_the_main_loop_leaves_rounds_to_their_lane(handlers):
    round_job, answer_job = add_job("workshop_step"), add_job("assistant_reply")
    loop = worker.Worker()
    loop.skip = worker.SLOW_KINDS
    assert loop.run_jobs() == 1
    assert handlers == ["assistant_reply"] and status(round_job) == "queued"
    assert loop.run_jobs(only=worker.SLOW_KINDS) == 1
    assert handlers == ["assistant_reply", "workshop_step"] and status(answer_job) == "done"


def test_the_lane_takes_only_rounds(handlers):
    answer_job = add_job("assistant_reply")
    assert worker.Worker().run_jobs(only=worker.SLOW_KINDS) == 0
    assert status(answer_job) == "queued"


def test_a_running_round_does_not_hold_up_an_assistant_answer(monkeypatch):
    """The round can only end once the answer is done: in one line this would never finish."""
    answered, round_started = threading.Event(), threading.Event()

    def slow_round(payload):
        round_started.set()
        assert answered.wait(timeout=10), "the assistant waited behind the round"

    monkeypatch.setitem(HANDLERS, "workshop_step", slow_round)
    monkeypatch.setitem(HANDLERS, "assistant_reply", lambda payload: answered.set())
    round_job = add_job("workshop_step")
    loop = worker.Worker()
    loop.skip = worker.SLOW_KINDS
    lane = threading.Thread(target=loop.run_jobs, kwargs={"only": worker.SLOW_KINDS})
    lane.start()
    assert round_started.wait(timeout=10)

    answer_job = add_job("assistant_reply")
    assert loop.run_jobs() == 1
    lane.join(timeout=10)
    assert status(answer_job) == "done" and status(round_job) == "done"


def test_the_forever_loop_starts_the_lane(monkeypatch):
    started = []
    monkeypatch.setattr(worker.Worker, "run_slow_lane", lambda self: started.append(self.skip))

    def stop(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.Worker, "run_cycle", stop)
    loop = worker.Worker()
    with pytest.raises(KeyboardInterrupt):
        loop.run_forever()
    assert loop.skip == worker.SLOW_KINDS and started


def test_once_runs_everything_in_one_line(handlers):
    add_job("workshop_step"), add_job("assistant_reply")
    assert worker.Worker().run_cycle() == 2
    assert handlers == ["workshop_step", "assistant_reply"]


# ---------------------------------------------------------------- upgrading a database

def rows(table: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(f'SELECT * FROM "{table}" ORDER BY 1'))]


def previous_release(history_days_ago: int = 0) -> None:
    """A database as the release before the Workshop leaves it: no Workshop tables."""
    seed.main()
    timeutils.freeze_time(NOW - timedelta(days=history_days_ago))
    seed_history.main()
    timeutils.freeze_time(NOW)
    tables = [SQLModel.metadata.tables[name] for name in WORKSHOP_TABLES]
    SQLModel.metadata.drop_all(engine, tables=tables)   # the seeds made them: this release's code


def test_upgrade_keeps_old_rows_and_adds_the_workshop(monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    previous_release()
    assert not set(WORKSHOP_TABLES) & set(inspect(engine).get_table_names())
    old_tables = ("user", "bike", "rental", "rentalrate", "orders")
    before = {t: rows(t) for t in old_tables}

    init_database()                  # what every start does
    assert set(WORKSHOP_TABLES) <= set(inspect(engine).get_table_names())
    assert {t: rows(t) for t in old_tables} == before

    seed_workshop.main()
    assert len(rows("supplier")) == 10 and rows("workshopcase")
    for table, old in before.items():
        assert set(old) <= set(rows(table)), f"seed_workshop changed a row in {table}"

    seed_workshop.main()             # a second run does nothing
    assert len(rows("supplier")) == 10


def test_seed_works_when_the_history_is_weeks_old(monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    previous_release(history_days_ago=30)
    init_database()
    seed_workshop.main()
    assert rows("workshopcase")


def test_seed_without_history_says_what_to_run(monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    with pytest.raises(SystemExit, match="seed_history"):
        seed_workshop.main()
