"""S7 sales, S8 reservation expiry by the scheduler (SPEC §11)."""
from datetime import timedelta

from sqlmodel import Session, select

from api import timeutils
from api.database import engine
from api.models.models import Bike, BikeStatus, JobRun, Order, OrderStatus
from api.services.order_service import OrderService
from scripts import scheduler

from .conftest import NOW, auth, make_user


def reserve(client, headers, bike_id):
    return client.post("/api/orders", json={"bike_id": bike_id}, headers=headers)


# ---------------------------------------------------------------- S7

def test_reserve_then_others_get_409(client, shop, db):
    bike = shop["bikes"]["s1"].id
    r = reserve(client, shop["customer"], bike)
    assert r.status_code == 200
    assert r.json()["status"] == "reserved"
    assert r.json()["expires_at"] == "2026-11-09T09:00:00+01:00"   # 7 days
    db.expire_all()  # this session still holds the bike from before the API call
    assert db.get(Bike, bike).status == BikeStatus.reserved
    make_user(db, "finn")
    r = reserve(client, auth(client, "finn"), bike)
    assert r.status_code == 409 and "already reserved" in r.json()["detail"]


def test_owner_cancel_frees_the_bike(client, shop, db):
    bike = shop["bikes"]["s1"].id
    order = reserve(client, shop["customer"], bike).json()
    r = client.post(f"/api/orders/{order['id']}/cancel", headers=shop["customer"])
    assert r.json()["status"] == "cancelled"
    db.expire_all()
    assert db.get(Bike, bike).status == BikeStatus.available


def test_complete_sells_and_hides(client, shop):
    bike = shop["bikes"]["s1"].id
    order = reserve(client, shop["customer"], bike).json()
    r = client.post(f"/staff/orders/{order['id']}/complete", headers=shop["staff"])
    assert r.json()["status"] == "completed"
    codes = [b["code"] for b in client.get("/api/bikes", headers=shop["customer"]).json()]
    assert "S-CITY-01" not in codes


def test_rental_bike_cannot_be_reserved(client, shop):
    assert reserve(client, shop["customer"], shop["bikes"]["r1"].id).status_code == 409


# ---------------------------------------------------------------- S8

def _order_reserved_at(client, shop, when):
    timeutils.freeze_time(when)
    headers = auth(client, "carla", name=f"k{when:%d%H%M}")
    order = reserve(client, headers, shop["bikes"]["s1"].id).json()
    timeutils.freeze_time(NOW)
    return order


def _order(order_id):
    with Session(engine) as db:
        order = db.get(Order, order_id)
        return order.status, db.get(Bike, order.bike_id).status


def test_expires_after_7_days(client, shop):
    order = _order_reserved_at(client, shop, NOW - timedelta(days=7, minutes=1))
    assert scheduler.run_once() == 1
    assert _order(order["id"]) == (OrderStatus.expired, BikeStatus.available)
    with Session(engine) as db:
        assert db.get(JobRun, "expire-reservations").last_result == "expired 1 orders"


def test_six_days_stays_reserved(client, shop):
    order = _order_reserved_at(client, shop, NOW - timedelta(days=6))
    assert scheduler.run_once() == 0
    assert _order(order["id"]) == (OrderStatus.reserved, BikeStatus.reserved)


def test_running_twice_changes_nothing_more(client, shop):
    _order_reserved_at(client, shop, NOW - timedelta(days=8))
    assert scheduler.run_once() == 1
    assert scheduler.run_once() == 0


def test_complete_and_expire_never_both(client, shop):
    """Staff completes first; the job then finds nothing. Order and bike agree."""
    order = _order_reserved_at(client, shop, NOW - timedelta(days=8))
    assert client.post(f"/staff/orders/{order['id']}/complete", headers=shop["staff"]).status_code == 200
    assert scheduler.run_once() == 0
    assert _order(order["id"]) == (OrderStatus.completed, BikeStatus.sold)


def test_expire_first_then_complete_is_409(client, shop):
    order = _order_reserved_at(client, shop, NOW - timedelta(days=8))
    assert scheduler.run_once() == 1
    r = client.post(f"/staff/orders/{order['id']}/complete", headers=shop["staff"])
    assert r.status_code == 409
    assert _order(order["id"]) == (OrderStatus.expired, BikeStatus.available)


def test_failing_run_is_recorded_and_next_run_works(client, shop, monkeypatch):
    def boom(self, db):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(OrderService, "expire_reservations", boom)
    assert scheduler.run_once() is None
    with Session(engine) as db:
        run = db.get(JobRun, "expire-reservations")
        assert run.last_ok is False and "disk on fire" in run.last_result
    monkeypatch.undo()
    assert scheduler.run_once() == 0
    with Session(engine) as db:
        assert db.get(JobRun, "expire-reservations").last_ok is True


def test_health_shows_last_run(client):
    scheduler.run_once()
    body = client.get("/health").json()
    assert body["scheduler"]["last_ok"] is True
    assert body["scheduler"]["last_run_at"] == "2026-11-02T09:00:00+01:00"


def test_reservation_limit(client, shop, db):
    from .conftest import make_bike
    from api.models.models import Purpose
    ids = [shop["bikes"]["s1"].id] + [make_bike(db, f"S-X-{i}", purpose=Purpose.sale, price="500").id for i in range(2)]
    assert reserve(client, shop["customer"], ids[0]).status_code == 200
    assert reserve(client, shop["customer"], ids[1]).status_code == 200
    r = reserve(client, shop["customer"], ids[2])
    assert r.status_code == 409 and "limit is 2" in r.json()["detail"]
