"""S9 seed, S11 BFH inference connection (SPEC §11)."""
import logging

import httpx
from sqlmodel import Session, func, select

from api.database import engine
from api.models.models import Bike, Order, Rental, RentalRate, User
from api.services import inference_service
from api.services.inference_service import InferenceService
from scripts import seed

from .conftest import auth


# ---------------------------------------------------------------- S9

def _counts():
    with Session(engine) as db:
        return tuple(db.exec(select(func.count()).select_from(t)).one() for t in (User, Bike, RentalRate, Rental, Order))


def test_seed_twice_same_counts(monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    first = _counts()
    seed.main()
    assert _counts() == first
    assert first == (4, 35, 7, 7, 2)


def test_seeded_board_has_work_to_do(client, monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    r = client.post("/auth/generate-key", json={"username": "staff", "password": "staff-pass-123", "name": "t"})
    staff = {"Authorization": f"Bearer {r.json()['api_key']}"}
    today = client.get("/staff/rentals", params={"date": "2026-11-02"}, headers=staff).json()
    statuses = {r["status"] for r in today}
    assert {"booked", "active"} <= statuses                          # a pick-up and a return today
    summary = client.get("/staff/inventory", headers=staff).json()
    assert summary["overdue_rentals"] and summary["at_risk_bookings"]
    assert summary["orders_expiring_within_24h"]


def test_demo_customer_can_still_book(client, monkeypatch):
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    r = client.post("/auth/generate-key", json={"username": "customer", "password": "customer-pass-123", "name": "t"})
    headers = {"Authorization": f"Bearer {r.json()['api_key']}"}
    bikes = client.get("/api/availability", params={"start_at": "2026-11-07T10:00", "end_at": "2026-11-07T15:00",
                                                    "category": "ebike"}, headers=headers).json()["bikes"]
    r = client.post("/api/rentals", json={"bike_id": bikes[0]["bike"]["id"], "start_at": "2026-11-07T10:00",
                                          "end_at": "2026-11-07T15:00"}, headers=headers)
    assert r.status_code == 200


# ---------------------------------------------------------------- S11

KEY = "sk-secret-test-key-0000"


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code, self._body = status_code, body or {}

    def json(self):
        return self._body


def service(**overrides):
    args = {"base_url": "https://inference.example/v1", "api_key": KEY, "model": "gpt-oss:120b"} | overrides
    return InferenceService(**args)


def fake_get(status_code, models=("gpt-oss:120b",), calls=None):
    def _get(url, headers, timeout):
        if calls is not None:
            calls.append(url)
        if status_code == "boom":
            raise httpx.ConnectError("no route")
        return FakeResponse(status_code, {"data": [{"id": m} for m in models]})
    return _get


def test_ok(monkeypatch):
    monkeypatch.setattr(inference_service.httpx, "get", fake_get(200))
    assert service().check() == "ok"


def test_not_configured_and_app_still_healthy(client):
    assert service(api_key="").check() == "not_configured"
    body = client.get("/health")
    assert body.status_code == 200 and body.json()["inference"] == "not_configured"


def test_unauthorized(monkeypatch):
    monkeypatch.setattr(inference_service.httpx, "get", fake_get(401))
    assert service().check() == "unauthorized"


def test_model_missing(monkeypatch):
    monkeypatch.setattr(inference_service.httpx, "get", fake_get(200, models=("gemma-4-26b",)))
    assert service().check() == "model_missing"


def test_unreachable(monkeypatch):
    monkeypatch.setattr(inference_service.httpx, "get", fake_get("boom"))
    assert service().check() == "unreachable"


def test_cached_for_60_seconds(monkeypatch):
    calls = []
    monkeypatch.setattr(inference_service.httpx, "get", fake_get(200, calls=calls))
    s = service()
    s.check()
    s.check()
    assert len(calls) == 1


def test_key_never_in_logs_or_health(client, monkeypatch, caplog):
    monkeypatch.setattr(inference_service.httpx, "get", fake_get(401))
    caplog.set_level(logging.DEBUG)
    s = service()
    s.check()
    assert KEY not in caplog.text
    assert KEY not in client.get("/health").text
    assert KEY not in repr(s.__dict__.get("base_url"))


def test_client_points_at_base_url():
    client = service().get_client()
    assert str(client.base_url).rstrip("/") == "https://inference.example/v1"


def test_seeded_rentals_follow_shop_rules(monkeypatch):
    """Example data should not break the rules the API enforces."""
    from api.config import OPENING_HOURS
    from api.timeutils import to_local
    monkeypatch.setenv("SEED_STAFF_PASSWORD", "staff-pass-123")
    monkeypatch.setenv("SEED_CUSTOMER_PASSWORD", "customer-pass-123")
    seed.main()
    with Session(engine) as db:
        for r in db.exec(select(Rental)).all():
            for t in (r.start_at, r.end_at):
                local = to_local(t)
                assert local.minute % 15 == 0
                opens, closes = OPENING_HOURS[local.weekday()]
                assert opens <= local.time() <= closes
            assert r.created_at <= r.start_at
        for o in db.exec(select(Order)).all():
            assert 9 <= to_local(o.expires_at).hour <= 18
