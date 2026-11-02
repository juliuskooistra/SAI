"""S5 availability, quotes, bookings; S6 pick-up and return (SPEC §11)."""
import threading
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from api import timeutils
from api.database import engine
from api.models.models import User
from api.services.errors import Conflict
from api.services.rental_service import RentalService

from .conftest import NOW, SAT, SUN, auth, book, make_bike, make_user


def available_codes(client, headers, start, end, **filters):
    r = client.get("/api/availability", params={"start_at": start, "end_at": end, **filters}, headers=headers)
    assert r.status_code == 200, r.text
    return [b["bike"]["code"] for b in r.json()["bikes"]]


# ---------------------------------------------------------------- S5

def test_overlap_and_exclusive_end(client, shop):
    bike = shop["bikes"]["r1"]
    assert book(client, shop["customer"], bike.id, f"{SAT}T10:00", f"{SAT}T14:00").status_code == 200
    assert bike.code not in available_codes(client, shop["customer"], f"{SAT}T13:00", f"{SAT}T15:00")
    assert bike.code in available_codes(client, shop["customer"], f"{SAT}T14:00", f"{SAT}T16:00")


def test_availability_includes_price(client, shop):
    r = client.get("/api/availability", params={"start_at": f"{SAT}T10:00", "end_at": f"{SAT}T15:00"},
                   headers=shop["customer"]).json()
    assert {b["quote"]["total_chf"] for b in r["bikes"]} == {"35.00"}
    assert r["start_at"] == f"{SAT}T10:00:00+01:00"


def test_sunday_is_closed(client, shop):
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SUN}T10:00", f"{SUN}T12:00")
    assert r.status_code == 400
    assert r.json()["detail"].startswith("The shop is closed on Sundays")


def test_saturday_closes_at_16(client, shop):
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:00", f"{SAT}T17:00")
    assert r.status_code == 400
    assert "16:00" in r.json()["detail"]


def test_quarter_hour_grid(client, shop):
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:07", f"{SAT}T12:00")
    assert r.status_code == 400
    assert "quarter hour" in r.json()["detail"]


def test_holiday_is_closed(client, shop):
    timeutils.freeze_time(datetime(2026, 12, 20, 9, 0, tzinfo=timezone.utc))
    headers = auth(client, "carla", name="december")  # the fixture's key expired after 30 days
    r = book(client, headers, shop["bikes"]["r1"].id, "2026-12-25T10:00", "2026-12-25T12:00")
    assert r.status_code == 400
    assert "Christmas Day" in r.json()["detail"]


def test_too_long_and_too_far_ahead(client, shop):
    bike = shop["bikes"]["r1"].id
    assert book(client, shop["customer"], bike, f"{SAT}T10:00", "2026-11-23T10:00").status_code == 400
    assert book(client, shop["customer"], bike, "2027-01-09T10:00", "2027-01-09T12:00").status_code == 400


def test_timezone_offsets_are_respected(client, shop):
    # 09:00 UTC on Saturday is 10:00 in Zurich: inside opening hours.
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T09:00:00Z", f"{SAT}T11:00:00Z")
    assert r.status_code == 200
    assert r.json()["start_at"] == f"{SAT}T10:00:00+01:00"


def test_concurrent_bookings_only_one_wins(shop, db):
    """Two customers book the same bike at the same moment: BEGIN IMMEDIATE lets exactly one through."""
    bike_id = shop["bikes"]["r1"].id
    other = make_user(db, "dora")
    start = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)
    results, barrier = [], threading.Barrier(2)

    def attempt(user_id):
        with Session(engine) as session:
            barrier.wait()
            try:
                RentalService().book(session, user_id, bike_id, start, start + timedelta(hours=3))
                results.append("ok")
            except Conflict:
                results.append("conflict")

    customer_id = db.exec(select(User).where(User.username == "carla")).one().user_id
    threads = [threading.Thread(target=attempt, args=(uid,)) for uid in (customer_id, other.user_id)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["conflict", "ok"]


def test_fourth_open_rental_is_409(client, shop, db):
    ids = [shop["bikes"]["r1"].id, shop["bikes"]["r2"].id,
           make_bike(db, "R-CITY-03").id, make_bike(db, "R-CITY-04").id]
    for bike_id in ids[:3]:
        assert book(client, shop["customer"], bike_id, f"{SAT}T10:00", f"{SAT}T12:00").status_code == 200
    r = book(client, shop["customer"], ids[3], f"{SAT}T10:00", f"{SAT}T12:00")
    assert r.status_code == 409
    assert "limit is 3" in r.json()["detail"]


def test_cancel_own_but_not_others(client, shop, db):
    rental = book(client, shop["customer"], shop["bikes"]["r1"].id, "2026-11-03T10:00", "2026-11-03T12:00").json()
    make_user(db, "eve")
    eve = auth(client, "eve")
    assert client.post(f"/api/rentals/{rental['id']}/cancel", headers=eve).status_code == 404
    assert client.get(f"/api/rentals/{rental['id']}", headers=eve).status_code == 404
    r = client.post(f"/api/rentals/{rental['id']}/cancel", headers=shop["customer"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_customer_cannot_cancel_after_start(client, shop):
    rental = book(client, shop["customer"], shop["bikes"]["r1"].id, "2026-11-02T10:00", "2026-11-02T12:00").json()
    timeutils.freeze_time(NOW + timedelta(hours=2))  # 11:00 Zurich
    r = client.post(f"/api/rentals/{rental['id']}/cancel", headers=shop["customer"])
    assert r.status_code == 409


def test_bike_in_maintenance_cannot_be_booked(client, shop):
    bike = shop["bikes"]["r1"].id
    client.patch(f"/staff/bikes/{bike}", json={"status": "maintenance"}, headers=shop["staff"])
    assert book(client, shop["customer"], bike, f"{SAT}T10:00", f"{SAT}T12:00").status_code == 409


def test_sale_bike_cannot_be_rented(client, shop):
    r = book(client, shop["customer"], shop["bikes"]["s1"].id, f"{SAT}T10:00", f"{SAT}T12:00")
    assert r.status_code == 409


# ---------------------------------------------------------------- S6

def test_pickup_only_on_start_day(client, shop):
    today = book(client, shop["customer"], shop["bikes"]["r1"].id, "2026-11-02T10:00", "2026-11-02T13:00").json()
    tomorrow = book(client, shop["customer"], shop["bikes"]["r2"].id, "2026-11-03T10:00", "2026-11-03T13:00").json()
    r = client.post(f"/staff/rentals/{today['id']}/pickup", headers=shop["staff"])
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["picked_up_at"]
    assert client.post(f"/staff/rentals/{tomorrow['id']}/pickup", headers=shop["staff"]).status_code == 409


def _picked_up_3h_rental(client, shop):
    rental = book(client, shop["customer"], shop["bikes"]["r1"].id, "2026-11-02T10:00", "2026-11-02T13:00").json()
    timeutils.freeze_time(datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))  # 10:00 Zurich
    client.post(f"/staff/rentals/{rental['id']}/pickup", headers=shop["staff"])
    return rental


def test_late_return_is_charged(client, shop):
    rental = _picked_up_3h_rental(client, shop)
    timeutils.freeze_time(datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc))  # 15:00 Zurich, 2 h late
    r = client.post(f"/staff/rentals/{rental['id']}/return", headers=shop["staff"])
    assert r.status_code == 200
    assert r.json()["final_price_chf"] == "35.00"   # 5 h, capped at the daily rate


def test_early_return_gets_no_refund(client, shop):
    rental = _picked_up_3h_rental(client, shop)
    timeutils.freeze_time(datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc))  # 12:00 Zurich, 1 h early
    r = client.post(f"/staff/rentals/{rental['id']}/return", headers=shop["staff"])
    assert r.json()["final_price_chf"] == "24.00"


def test_overdue_is_listed_and_blocks(client, shop):
    rental = _picked_up_3h_rental(client, shop)
    timeutils.freeze_time(datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc))  # next day
    overdue = client.get("/staff/rentals", params={"overdue": "true"}, headers=shop["staff"]).json()
    assert [r["id"] for r in overdue] == [rental["id"]] and overdue[0]["overdue"]
    codes = available_codes(client, shop["customer"], f"{SAT}T10:00", f"{SAT}T12:00")
    assert "R-CITY-01" not in codes
    r = book(client, shop["customer"], shop["bikes"]["r1"].id, f"{SAT}T10:00", f"{SAT}T12:00")
    assert r.status_code == 409 and "hasn't been returned" in r.json()["detail"]


def test_board_by_date(client, shop):
    book(client, shop["customer"], shop["bikes"]["r1"].id, "2026-11-02T10:00", "2026-11-02T13:00")
    book(client, shop["customer"], shop["bikes"]["r2"].id, "2026-11-03T10:00", "2026-11-03T13:00")
    today = client.get("/staff/rentals", params={"date": "2026-11-02"}, headers=shop["staff"]).json()
    assert [r["bike_code"] for r in today] == ["R-CITY-01"]
    assert today[0]["username"] == "carla"
