"""S3 catalogue and inventory, S4 pricing (SPEC §11)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from api.models.models import BikeStatus, Category, Purpose
from api.services.errors import InvalidInput
from api.services.pricing_service import rental_price, validate_rate

from .conftest import SAT, book, make_bike


# ---------------------------------------------------------------- S3

def test_search_sale_bikes_under_a_price(client, shop, db):
    make_bike(db, "S-ROAD-01", purpose=Purpose.sale, category=Category.road, price="2500")
    make_bike(db, "S-OLD-01", purpose=Purpose.sale, price="300", status=BikeStatus.retired)
    make_bike(db, "S-GONE-01", purpose=Purpose.sale, price="400", status=BikeStatus.sold)
    r = client.get("/api/bikes", params={"purpose": "sale", "max_price_chf": 1500}, headers=shop["customer"])
    assert [b["code"] for b in r.json()] == ["S-CITY-01"]


def test_text_search(client, shop):
    r = client.get("/api/bikes", params={"q": "R-CITY-02"}, headers=shop["customer"])
    assert [b["code"] for b in r.json()] == ["R-CITY-02"]


def test_bike_detail_has_rate_for_rental_bikes(client, shop):
    r = client.get(f"/api/bikes/{shop['bikes']['r1'].id}", headers=shop["customer"]).json()
    assert r["rental_rate"]["daily_chf"] == "35.00"
    s = client.get(f"/api/bikes/{shop['bikes']['s1'].id}", headers=shop["customer"]).json()
    assert s["rental_rate"] is None


def test_sale_bike_needs_a_price(client, shop):
    r = client.post("/staff/bikes", headers=shop["staff"], json={
        "code": "S-X-1", "name": "X", "brand": "Y", "category": "city", "frame_size": "M",
        "color": "red", "year": 2025, "purpose": "sale"})
    assert r.status_code == 422


def test_retire_with_future_booking_is_409_maintenance_is_at_risk(client, shop):
    bike = shop["bikes"]["r1"].id
    assert book(client, shop["customer"], bike, f"{SAT}T10:00", f"{SAT}T12:00").status_code == 200
    assert client.post(f"/staff/bikes/{bike}/retire", headers=shop["staff"]).status_code == 409
    r = client.patch(f"/staff/bikes/{bike}", json={"status": "maintenance"}, headers=shop["staff"])
    assert r.status_code == 200
    at_risk = client.get("/staff/inventory", headers=shop["staff"]).json()["at_risk_bookings"]
    assert [b["bike_id"] for b in at_risk] == [bike]


def test_sale_bike_status_cannot_be_patched(client, shop):
    r = client.patch(f"/staff/bikes/{shop['bikes']['s1'].id}", json={"status": "sold"}, headers=shop["staff"])
    assert r.status_code == 400


def test_retired_bike_hidden_from_customers(client, shop):
    bike = shop["bikes"]["r2"].id
    assert client.post(f"/staff/bikes/{bike}/retire", headers=shop["staff"]).status_code == 200
    assert client.get(f"/api/bikes/{bike}", headers=shop["customer"]).status_code == 404
    assert bike in [b["id"] for b in client.get("/staff/bikes", headers=shop["staff"]).json()]


# ---------------------------------------------------------------- S4

T0 = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("duration, expected", [
    (timedelta(hours=1), "8.00"),
    (timedelta(hours=3), "24.00"),
    (timedelta(hours=5), "35.00"),
    (timedelta(hours=26), "51.00"),
    (timedelta(days=3), "105.00"),
    (timedelta(minutes=61), "16.00"),   # every started hour counts
])
def test_price_table_from_spec(duration, expected):
    assert rental_price(T0, T0 + duration, Decimal("8"), Decimal("35")).total_chf == Decimal(expected)


def test_daily_above_24_hourly_rejected(client, shop):
    with pytest.raises(InvalidInput):
        validate_rate(Decimal("1"), Decimal("30"))
    r = client.put("/staff/rental-rates/city", json={"hourly_chf": "1", "daily_chf": "30"}, headers=shop["staff"])
    assert r.status_code == 422


def test_booking_keeps_its_price_after_a_rate_change(client, shop):
    bike = shop["bikes"]["r1"].id
    rental = book(client, shop["customer"], bike, f"{SAT}T09:00", f"{SAT}T14:00").json()
    assert rental["quoted_price_chf"] == "35.00"
    r = client.put("/staff/rental-rates/city", json={"hourly_chf": "8", "daily_chf": "40"}, headers=shop["staff"])
    assert r.status_code == 200
    again = client.get(f"/api/rentals/{rental['id']}", headers=shop["customer"]).json()
    assert again["quoted_price_chf"] == "35.00"


def test_empty_names_rejected(client, shop):
    r = client.post("/staff/bikes", headers=shop["staff"], json={
        "code": "R-X-1", "name": "", "brand": "", "category": "city", "frame_size": "M",
        "color": "", "year": 2025, "purpose": "rental"})
    assert r.status_code == 422


def test_retired_bike_cannot_be_edited(client, shop):
    bike = shop["bikes"]["r2"].id
    client.post(f"/staff/bikes/{bike}/retire", headers=shop["staff"])
    r = client.patch(f"/staff/bikes/{bike}", json={"status": "available"}, headers=shop["staff"])
    assert r.status_code == 409 and "retired" in r.json()["detail"]
