"""
Shared test setup: a fresh SQLite file per test, a frozen clock, and helpers
to create users, keys, bikes and rates.

The clock is frozen at Monday 2 Nov 2026, 09:00 Zurich (08:00 UTC), so
"next Saturday" is 7 Nov 2026 and Sunday is 8 Nov.
"""
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

# Point the app at a throwaway database *before* anything imports api.config.
_TMP = tempfile.mkdtemp(prefix="bikeshop-tests-")
os.environ["BIKESHOP_DATA_DIR"] = _TMP
os.environ.pop("MLMP_API_KEY", None)

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

from api import timeutils
from api.database import engine
from api.expose_api import app
from api.models.models import Bike, Category, Condition, FrameSize, Purpose, RentalRate, Role, User
from api.services.auth_service import AuthService
from api.services.inference_service import InferenceService

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)   # Mon 09:00 Zurich
SAT = "2026-11-07"
SUN = "2026-11-08"
PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fresh_state():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    timeutils.freeze_time(NOW)
    InferenceService.clear_cache()
    yield
    timeutils.freeze_time(None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with Session(engine) as session:
        yield session


def make_user(db: Session, username: str, role: Role = Role.customer, tokens: float | None = None) -> User:
    user = AuthService().register_user(username, f"{username}@test.ch", PASSWORD, db, role=role)
    if tokens is not None:
        user.token_balance = tokens
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def auth(client: TestClient, username: str, name: str = "test") -> dict:
    r = client.post("/auth/generate-key", json={"username": username, "password": PASSWORD, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def make_bike(db: Session, code: str, purpose: Purpose = Purpose.rental, category: Category = Category.city,
              price: str | None = None, **extra) -> Bike:
    bike = Bike(code=code, name=f"Bike {code}", brand="Test", category=category, frame_size=FrameSize.M,
                color="red", year=2024, purpose=purpose,
                condition=Condition.new if purpose == Purpose.sale else Condition.used,
                sale_price_chf=Decimal(price) if price else None, **extra)
    db.add(bike)
    db.commit()
    db.refresh(bike)
    return bike


def make_rate(db: Session, category: Category = Category.city, hourly: str = "8", daily: str = "35",
              deposit: str = "100") -> RentalRate:
    rate = RentalRate(category=category, hourly_chf=Decimal(hourly), daily_chf=Decimal(daily),
                      deposit_chf=Decimal(deposit))
    db.add(rate)
    db.commit()
    return rate


@pytest.fixture
def shop(db, client):
    """A customer, a staff member (both with keys), a city rate, two rental bikes and one sale bike."""
    make_user(db, "carla")
    make_user(db, "sam", role=Role.staff)
    make_rate(db)
    bikes = {
        "r1": make_bike(db, "R-CITY-01"),
        "r2": make_bike(db, "R-CITY-02"),
        "s1": make_bike(db, "S-CITY-01", purpose=Purpose.sale, price="900"),
    }
    return {"customer": auth(client, "carla"), "staff": auth(client, "sam"), "bikes": bikes}


def book(client, headers, bike_id, start, end):
    return client.post("/api/rentals", json={"bike_id": bike_id, "start_at": start, "end_at": end}, headers=headers)
