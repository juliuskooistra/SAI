"""S14 queue and worker, S15 email notifications (SPEC §11)."""
import logging
import threading
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from sqlmodel import Session, select

from api import config, timeutils
from api.database import engine
from api.jobqueue import queue
from api.jobqueue.handlers import HANDLERS, register
from api.mail import LoggingMailer, MailgunMailer, make_mailer
from api.models.models import AnalyticsEvent, Job, JobRun, Order, OrderStatus, User
from scripts import worker as worker_mod
from scripts.worker import Worker, run_job

from .conftest import NOW, SAT, auth, book, make_user


def add_job(kind="test_kind", payload=None, user_id=None) -> int:
    with Session(engine) as db:
        job = queue.enqueue(db, kind, payload or {}, user_id=user_id)
        db.commit()
        return job.id


def get(job_id) -> Job:
    with Session(engine) as db:
        return db.get(Job, job_id)


def claim(worker_id="w1"):
    with Session(engine) as db:
        return queue.claim(db, worker_id)


@pytest.fixture
def handler():
    """A test handler whose behaviour each test sets."""
    calls = []
    behaviour = {"raise": None}

    def run(payload):
        calls.append(payload)
        if behaviour["raise"]:
            raise behaviour["raise"]
        return {"echo": payload}
    register("test_kind")(run)
    yield {"calls": calls, "behaviour": behaviour}
    HANDLERS.pop("test_kind", None)


def email_jobs():
    with Session(engine) as db:
        return db.exec(select(Job).where(Job.kind == "send_email").order_by(Job.id)).all()


# ---------------------------------------------------------------- S14 queue

def test_two_concurrent_claims_one_winner():
    job_id = add_job()
    results, barrier = [], threading.Barrier(2)

    def attempt(worker_id):
        with Session(engine) as session:
            barrier.wait()
            results.append(queue.claim(session, worker_id))

    threads = [threading.Thread(target=attempt, args=(w,)) for w in ("w1", "w2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    won = [r for r in results if r is not None]
    assert len(won) == 1 and won[0].id == job_id and won[0].attempt == 1
    job = get(job_id)
    assert job.status == "running" and job.attempts == 1 and job.worker_id in ("w1", "w2")


def test_claim_takes_oldest_and_skips_future_run_after():
    first, second = add_job(), add_job()
    with Session(engine) as db:
        db.get(Job, first).run_after = NOW + timedelta(minutes=5)
        db.commit()
    assert claim().id == second
    assert claim() is None


def test_success_stores_result(handler):
    job_id = add_job(payload={"x": 1})
    assert Worker().run_jobs() == 1
    job = get(job_id)
    assert job.status == "done" and job.result == {"echo": {"x": 1}} and job.finished_at is not None


def test_retry_with_backoff_then_failed_after_3(handler):
    handler["behaviour"]["raise"] = RuntimeError("smtp down")
    job_id = add_job()
    assert run_job(claim()) == "retry"
    job = get(job_id)
    assert job.status == "queued" and job.attempts == 1 and "smtp down" in job.error
    assert job.run_after.replace(tzinfo=None) == (NOW + timedelta(seconds=30)).replace(tzinfo=None)
    assert claim() is None                       # not before run_after

    timeutils.freeze_time(NOW + timedelta(seconds=30))
    assert run_job(claim()) == "retry"
    assert get(job_id).run_after.replace(tzinfo=None) == (NOW + timedelta(seconds=90)).replace(tzinfo=None)

    timeutils.freeze_time(NOW + timedelta(seconds=90))
    assert run_job(claim()) == "failed"
    job = get(job_id)
    assert job.status == "failed" and job.attempts == 3 and job.error == "RuntimeError: smtp down"
    assert len(handler["calls"]) == 3


def test_error_is_truncated(handler):
    handler["behaviour"]["raise"] = RuntimeError("x" * 5000)
    job_id = add_job()
    run_job(claim())
    assert len(get(job_id).error) == config.JOB_MAX_ERROR_CHARS


def _stale(job_id, minutes=3):
    with Session(engine) as db:
        db.get(Job, job_id).heartbeat_at = NOW - timedelta(minutes=minutes)
        db.commit()


def test_reaper_requeues_stale_job_or_fails_it():
    job_id = add_job()
    claim()
    _stale(job_id)
    Worker().reap()
    job = get(job_id)
    assert job.status == "queued" and "stopped while running attempt 1" in job.error

    with Session(engine) as db:      # last attempt: the reaper gives up
        db.get(Job, job_id).attempts = 2
        db.commit()
    claim()
    _stale(job_id)
    Worker().reap()
    job = get(job_id)
    assert job.status == "failed" and "gave up after 3 attempts" in job.error


def test_reaper_leaves_fresh_jobs_alone():
    job_id = add_job()
    claim()
    _stale(job_id, minutes=1)
    Worker().reap()
    assert get(job_id).status == "running"


def test_fencing_old_worker_cannot_overwrite(handler):
    job_id = add_job()
    old = claim("old")
    _stale(job_id)
    Worker().reap()                               # requeued
    new = claim("new")                            # attempt 2
    with Session(engine) as db:
        assert queue.finish(db, old, {"stale": True}) is False
        assert queue.heartbeat(db, old) is False
        assert queue.fail(db, old, "late error") is None
    job = get(job_id)
    assert job.status == "running" and job.worker_id == "new" and job.result is None
    assert run_job(new) == "done"


def test_unknown_kind_fails_at_once():
    job_id = add_job(kind="llm_task")             # deliberately unregistered (SPEC §8.2)
    assert run_job(claim()) == "failed"
    job = get(job_id)
    assert job.status == "failed" and job.attempts == 1
    assert job.error == "No handler for job kind 'llm_task'"


def test_outcome_logged_with_fields(handler, caplog):
    add_job()
    with caplog.at_level(logging.INFO, logger="worker"):
        Worker().run_jobs()
    rec = [r for r in caplog.records if getattr(r, "outcome", None) == "done"][0]
    assert rec.kind == "test_kind" and rec.attempt == 1 and isinstance(rec.duration_ms, int)


def test_job_ownership(client, shop, db):
    carla = db.exec(select(User).where(User.username == "carla")).one()
    job_id = add_job(kind="send_email", payload={"to": "carla@test.ch"}, user_id=carla.user_id)
    r = client.get(f"/api/jobs/{job_id}", headers=shop["customer"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "kind", "status", "attempts", "max_attempts", "user_id", "enqueued_at",
                         "started_at", "finished_at", "result", "error"}
    assert body["status"] == "queued" and body["enqueued_at"] == "2026-11-02T09:00:00+01:00"
    make_user(db, "eve")
    assert client.get(f"/api/jobs/{job_id}", headers=auth(client, "eve")).status_code == 404
    assert client.get("/api/jobs/9999", headers=shop["customer"]).status_code == 404


def test_staff_list_jobs(client, shop):
    add_job(kind="send_email")
    add_job(kind="llm_task")
    r = client.get("/staff/jobs", headers=shop["staff"])
    assert r.status_code == 200 and [j["kind"] for j in r.json()] == ["llm_task", "send_email"]
    assert [j["kind"] for j in client.get("/staff/jobs?kind=send_email", headers=shop["staff"]).json()] == ["send_email"]
    assert client.get("/staff/jobs?status=failed", headers=shop["staff"]).json() == []
    assert client.get("/staff/jobs", headers=shop["customer"]).status_code == 403
    assert "payload" not in r.json()[0]


def test_operation_ids(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/jobs/{job_id}"]["get"]["operationId"] == "get_my_job"
    assert paths["/staff/jobs"]["get"]["operationId"] == "list_jobs"


def test_worker_cycle_expires_and_health_shows_worker_and_queue(client, shop):
    timeutils.freeze_time(NOW - timedelta(days=8))
    order = client.post("/api/orders", json={"bike_id": shop["bikes"]["s1"].id}, headers=shop["customer"]).json()
    timeutils.freeze_time(NOW)
    Worker().run_cycle()
    with Session(engine) as db:
        assert db.get(Order, order["id"]).status == OrderStatus.expired
        assert db.get(JobRun, "expire-reservations").last_result == "expired 1 orders"
    body = client.get("/health").json()
    assert body["scheduler"]["last_ok"] is True
    assert body["worker"]["last_seen"] == "2026-11-02T09:00:00+01:00"
    # reserved + expired emails, both sent (logging mailer) in this cycle
    assert body["queue"] == {"queued": 0, "running": 0, "done": 2, "failed": 0}


def test_health_before_worker_ever_ran(client):
    body = client.get("/health").json()
    assert body["worker"] == {"last_seen": None}
    assert body["queue"] == {"queued": 0, "running": 0, "done": 0, "failed": 0}


def test_expiry_runs_at_start_and_then_every_15_minutes(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_mod, "run_expiry", lambda: calls.append(1))
    w = Worker()
    w.run_scheduled()
    w.run_scheduled()
    assert len(calls) == 1
    timeutils.freeze_time(NOW + timedelta(minutes=15))
    w.run_scheduled()
    assert len(calls) == 2


def test_analytics_cleanup_once_a_day():
    with Session(engine) as db:
        db.add(AnalyticsEvent(day=date(2025, 11, 1), name="quote"))     # 366 days old
        db.add(AnalyticsEvent(day=date(2025, 11, 3), name="quote"))     # 364 days old
        db.commit()
    w = Worker()
    w.run_scheduled()
    with Session(engine) as db:
        assert [e.day for e in db.exec(select(AnalyticsEvent)).all()] == [date(2025, 11, 3)]
        assert db.get(JobRun, "analytics-cleanup").last_result == "deleted 1 events"
    assert w.last_cleanup_day == date(2026, 11, 2)


# ---------------------------------------------------------------- S15 email

def test_booking_enqueues_email_in_same_transaction(client, shop, db):
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:00", f"{SAT}T13:00")
    assert r.status_code == 200
    [job] = email_jobs()
    carla = db.exec(select(User).where(User.username == "carla")).one()
    assert job.status == "queued" and job.user_id == carla.user_id
    assert job.payload["to"] == "carla@test.ch"
    assert job.payload["subject"].startswith("Booking confirmed: Bike R-CITY-01")
    assert f"{config.PUBLIC_URL}/#/my" in job.payload["text"] and "#/my" in job.payload["html"]
    assert "CHF 24.00" in job.payload["text"]


def test_failed_booking_enqueues_nothing(client, shop):
    assert book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:00", f"{SAT}T13:00").status_code == 200
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T11:00", f"{SAT}T12:00")
    assert r.status_code == 409
    assert len(email_jobs()) == 1


def test_enqueue_fails_booking_rolls_back(client, shop, monkeypatch):
    """If queuing the email fails, the booking doesn't happen either."""
    from api.services import notification_service
    def boom(*a, **k):
        raise RuntimeError("queue broken")
    monkeypatch.setattr(notification_service.queue, "enqueue", boom)
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:00", f"{SAT}T13:00")
    assert r.status_code == 500
    monkeypatch.undo()
    assert client.get("/api/rentals", headers=shop["customer"]).json() == []
    assert email_jobs() == []


def test_reserve_enqueues_held_until_email(client, shop):
    client.post("/api/orders", json={"bike_id": shop["bikes"]["s1"].id}, headers=shop["customer"])
    [job] = email_jobs()
    assert job.payload["subject"] == "Reserved: Bike S-CITY-01, held until Mon 9 Nov 09:00"


def test_logging_mailer_without_key(client, shop, monkeypatch, caplog):
    monkeypatch.setattr(config, "MAILGUN_API_KEY", "")
    assert isinstance(make_mailer(), LoggingMailer)
    book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:00", f"{SAT}T13:00")
    with caplog.at_level(logging.INFO, logger="bikeshop.mail"):
        Worker().run_jobs()
    [job] = email_jobs()
    assert job.status == "done" and job.result == {"sent": False, "backend": "logging"}
    [line] = [r.getMessage() for r in caplog.records if r.name == "bikeshop.mail"]
    assert "@test.ch" in line and "Booking confirmed" in line
    assert "carla@" not in line                     # never the full address


def test_mailgun_request_shape(monkeypatch):
    monkeypatch.setattr(config, "MAILGUN_API_KEY", "key-123")
    monkeypatch.setattr(config, "MAILGUN_DOMAIN", "mail.kooistra.ch")
    monkeypatch.setattr(config, "MAILGUN_BASE_URL", "https://api.eu.mailgun.net/v3")
    monkeypatch.setattr(config, "MAIL_FROM", "BikeShop <bikeshop@mail.kooistra.ch>")
    mailer = make_mailer()
    assert isinstance(mailer, MailgunMailer)

    seen = {}
    def respond(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"id": "<1@mail.kooistra.ch>", "message": "Queued. Thank you."})
    mailer._client = httpx.Client(transport=httpx.MockTransport(respond))
    mailer.send(to="carla@example.ch", subject="Hi", text="Hello", html="<p>Hello</p>")

    req = seen["request"]
    assert str(req.url) == "https://api.eu.mailgun.net/v3/mail.kooistra.ch/messages"
    assert req.method == "POST"
    import base64
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b"api:key-123").decode()
    form = parse_qs(req.content.decode())
    assert form["from"] == ["BikeShop <bikeshop@mail.kooistra.ch>"]
    assert form["to"] == ["carla@example.ch"] and form["subject"] == ["Hi"]
    assert form["text"] == ["Hello"] and form["html"] == ["<p>Hello</p>"]


def test_mailgun_error_makes_job_retry(monkeypatch):
    monkeypatch.setattr(config, "MAILGUN_API_KEY", "bad")
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="Forbidden"))))
    job_id = add_job(kind="send_email", payload={"to": "a@example.ch", "subject": "s", "text": "t"})
    assert run_job(claim()) == "retry"
    assert "401" in get(job_id).error


def test_dot_test_address_is_skipped(monkeypatch):
    sent = []
    monkeypatch.setattr(LoggingMailer, "send", lambda self, **kw: sent.append(kw))
    job_id = add_job(kind="send_email", payload={"to": "demo@bikeshop.test", "subject": "s", "text": "t"})
    assert Worker().run_jobs() == 1
    job = get(job_id)
    assert job.status == "done" and job.result == {"skipped": ".test address"}
    assert sent == []


def test_expiry_enqueues_expired_email(client, shop):
    timeutils.freeze_time(NOW - timedelta(days=8))
    client.post("/api/orders", json={"bike_id": shop["bikes"]["s1"].id}, headers=shop["customer"])
    timeutils.freeze_time(NOW)
    assert worker_mod.run_expiry() == 1
    subjects = [j.payload["subject"] for j in email_jobs()]
    assert subjects[-1] == "Reservation expired: Bike S-CITY-01"
    assert worker_mod.run_expiry() == 0
    assert len(email_jobs()) == 2                   # the second run queues nothing
