"""S1 skeleton, S2 auth / roles / rate limit / billing (SPEC §11)."""
from sqlmodel import select

from api.config import DATA_DIR
from api.models.models import APIUsage, Role, User

from .conftest import SAT, auth, book, make_user


# ---------------------------------------------------------------- S1

def test_health_and_docs_are_public(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    docs = client.get("/docs")
    assert docs.status_code == 200 and "scalar" in docs.text.lower()


def test_database_file_is_created():
    assert (DATA_DIR / "bikeshop.db").exists()


# ---------------------------------------------------------------- S2: roles

def test_registration_makes_a_customer(client, db):
    r = client.post("/auth/register", json={"username": "neo", "email": "neo@test.ch", "password": "0123456789"})
    assert r.status_code == 200
    user = db.exec(select(User).where(User.username == "neo")).one()
    assert user.role == Role.customer


def test_customer_cannot_reach_staff(client, shop):
    r = client.get("/staff/inventory", headers=shop["customer"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Only shop staff can do this."


def test_staff_calls_are_free(client, shop):
    before = client.get("/billing/balance", headers=shop["staff"]).json()["current_balance"]
    assert client.get("/staff/inventory", headers=shop["staff"]).status_code == 200
    after = client.get("/billing/balance", headers=shop["staff"]).json()["current_balance"]
    assert before == after


def test_missing_key_is_401(client):
    assert client.get("/api/bikes").status_code == 401


# ---------------------------------------------------------------- S2: billing

def test_no_tokens_is_402_and_nothing_charged(client, db):
    make_user(db, "broke", tokens=0)
    headers = auth(client, "broke")
    r = client.get("/api/bikes", headers=headers)
    assert r.status_code == 402
    assert "Not enough API tokens" in r.json()["detail"]
    assert db.exec(select(APIUsage)).all() == []


def test_booking_costs_5_and_a_failed_booking_costs_nothing(client, shop):
    bike = shop["bikes"]["r1"].id
    balance = lambda: client.get("/billing/balance", headers=shop["customer"]).json()["current_balance"]
    start = balance()
    assert book(client, shop["customer"], bike, f"{SAT}T10:00", f"{SAT}T12:00").status_code == 200
    assert balance() == start - 5
    assert book(client, shop["customer"], bike, f"{SAT}T11:00", f"{SAT}T13:00").status_code == 409
    assert balance() == start - 5


def test_one_usage_row_per_billed_call(client, shop, db):
    client.get("/api/bikes", headers=shop["customer"])
    assert len(db.exec(select(APIUsage)).all()) == 1


def test_cancel_is_free(client, shop):
    bike = shop["bikes"]["r1"].id
    rental = book(client, shop["customer"], bike, f"{SAT}T10:00", f"{SAT}T12:00").json()
    r = client.post(f"/api/rentals/{rental['id']}/cancel", headers=shop["customer"])
    assert r.status_code == 200
    assert r.headers["X-Tokens-Consumed"] == "0.0"


# ---------------------------------------------------------------- S2: rate limit

def test_rate_limit_blocks_call_n_plus_1(client, db):
    user = make_user(db, "busy")
    user.requests_per_minute = 3
    db.add(user)
    db.commit()
    headers = auth(client, "busy")
    codes = [client.get("/api/bikes", headers=headers).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


# ---------------------------------------------------------------- S2: key management (fixed vs reference)

def test_my_keys_shows_only_own_keys(client, shop, db):
    make_user(db, "other")
    auth(client, "other", name="other-key")
    keys = client.get("/auth/my-keys", headers=shop["customer"]).json()["keys"]
    assert [k["name"] for k in keys] == ["test"]


def test_my_keys_needs_a_key(client):
    assert client.get("/auth/my-keys").status_code == 401


def test_revoked_key_stops_working(client, db):
    make_user(db, "leaver")
    headers = auth(client, "leaver", name="laptop")
    assert client.delete("/auth/revoke-key/laptop", headers=headers).status_code == 200
    assert client.get("/api/bikes", headers=headers).status_code == 401


def test_login_returns_role(client, shop):
    r = client.post("/auth/login", json={"username": "sam", "password": "correct-horse-battery"})
    assert r.json()["role"] == "staff"
