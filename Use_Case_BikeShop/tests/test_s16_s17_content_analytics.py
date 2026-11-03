"""
S16 help and legal pages, S17 analytics (SPEC §5.10, §6, §11).
"""
import re
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from api import timeutils
from api.config import FRONTEND_DIR
from api.content import mount_content_pages
from api.database import engine, init_database
from api.models.models import AnalyticsEvent, Purpose, User
from api.services import analytics_service

from .conftest import NOW, SAT, book, make_bike

PAGES = ["/help", "/help/getting-started", "/help/renting", "/help/buying", "/help/account",
         "/help/staff", "/legal/privacy", "/legal/terms"]


# ------------------------------------------------------------------ S16

def test_help_and_legal_pages_render(client):
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html"), path
        assert "<h1" in r.text and '<nav class="kw">' in r.text, path
    css = client.get("/_docs.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


def test_legal_pages_are_marked_as_drafts(client):
    for path in ["/legal/privacy", "/legal/terms"]:
        text = client.get(path).text
        assert "Draft, pending review" in text
        assert "BFH | W | AIRS lab" in text and "julius.kooistra@bfh.ch" in text


def test_pages_load_only_same_origin_assets(client):
    for path in PAGES:
        html = client.get(path).text
        # No scripts, no inline styles, no images or frames: nothing that loads by itself.
        assert "<script" not in html and "style=" not in html and "<style" not in html, path
        assert not re.search(r"<(img|iframe|video|audio|source|object|embed)\b", html), path
        assert " src=" not in html, path
        # The only <link> is the same-origin stylesheet.
        links = re.findall(r"<link [^>]*href=\"([^\"]+)\"", html)
        assert links == ["/_docs.css"], (path, links)
        # Plain <a> links may point anywhere; other hrefs must stay on this site.
        for href in re.findall(r"<a [^>]*href=\"([^\"]+)\"", html):
            assert not href.endswith(".md"), (path, href)


def test_cross_links_are_rewritten(client):
    index = client.get("/help").text
    for href in ["/help/getting-started", "/help/renting", "/help/buying", "/help/account",
                 "/help/staff", "/legal/privacy", "/legal/terms"]:
        assert f'href="{href}"' in index, href
    # A link to a heading in another article keeps its #fragment.
    assert 'href="/help/renting#how-the-price-is-calculated"' in client.get("/help/staff").text
    assert 'id="how-the-price-is-calculated"' in client.get("/help/renting").text


def test_a_route_exists_only_if_its_file_does(tmp_path: Path):
    (tmp_path / "help").mkdir()
    (tmp_path / "help" / "index.md").write_text("# Help\n\nSee [renting](renting.md).\n")
    app = FastAPI()
    mount_content_pages(app, docs_dir=tmp_path)   # no legal files, no articles
    client = TestClient(app)
    assert client.get("/help").status_code == 200
    assert client.get("/help/renting").status_code == 404
    assert client.get("/legal/privacy").status_code == 404
    assert client.get("/legal/terms").status_code == 404

    empty = FastAPI()
    mount_content_pages(empty, docs_dir=tmp_path / "nothing-here")
    assert TestClient(empty).get("/help").status_code == 404
    assert TestClient(empty).get("/_docs.css").status_code == 404


def test_api_paths_keep_priority_over_the_pages(client):
    assert client.get("/api/bikes").status_code == 401    # still the API
    assert client.get("/help/no-such-article").status_code == 404


def test_frontend_footer_links_to_help_privacy_terms(client):
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    footer = re.search(r"<footer.*?</footer>", html, re.S).group(0)
    for href in ["/help", "/legal/privacy", "/legal/terms"]:
        assert f'href="{href}"' in footer, href
    assert client.get("/").text == html


# ------------------------------------------------------------------ S17: recording

def events(db):
    db.expire_all()
    return db.exec(select(AnalyticsEvent).order_by(AnalyticsEvent.id)).all()


def test_view_quote_book_reserve_create_one_anonymous_event_each(client, db, shop):
    c, bike, sale = shop["customer"], shop["bikes"]["r1"], shop["bikes"]["s1"]
    period = {"bike_id": bike.id, "start_at": f"{SAT}T10:00", "end_at": f"{SAT}T15:00"}

    assert client.get("/api/bikes", headers=c).status_code == 200
    assert client.get(f"/api/bikes/{bike.id}", headers=c).status_code == 200
    assert client.post("/api/rentals/quote", json=period, headers=c).status_code == 200
    assert book(client, c, bike.id, period["start_at"], period["end_at"]).status_code == 200
    assert client.post("/api/orders", json={"bike_id": sale.id}, headers=c).status_code == 200

    got = [(e.name, e.bike_id, e.category, e.day) for e in events(db)]
    today = date(2026, 11, 2)
    assert got == [
        ("catalogue_view", None, None, today),
        ("bike_view", bike.id, "city", today),
        ("quote", bike.id, "city", today),
        ("booking", bike.id, "city", today),
        ("reservation", sale.id, "city", today),
    ]
    assert {e.channel for e in events(db)} == {"api"}
    # Anonymous by design: the table has no column that could identify anyone.
    # `channel` says how something happened (website/API or assistant), not who did it.
    assert set(AnalyticsEvent.model_fields) == {"id", "day", "name", "bike_id", "category", "channel"}


def test_bookings_by_channel_count_the_assistant(client, db, shop):
    from api.tools.assistant_tools import run_tool
    carla = db.exec(select(User).where(User.username == "carla")).first().user_id
    r1, r2 = shop["bikes"]["r1"], shop["bikes"]["r2"]
    assert book(client, shop["customer"], r1.id, f"{SAT}T10:00", f"{SAT}T15:00").status_code == 200
    assert run_tool("book_rental", {"bike_id": r2.id, "start_at": f"{SAT}T10:00", "end_at": f"{SAT}T15:00"},
                    db, carla)["status"] == "booked"

    body = client.get("/staff/analytics", params={"days": 7}, headers=shop["staff"]).json()
    assert body["bookings_by_channel"] == {"api": 1, "assistant": 1}
    assert body["totals"]["booking"] == 2


def test_init_database_adds_the_channel_column_to_an_old_table(db):
    # An analytics table from before `channel` existed, with one old event in it
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE analyticsevent DROP COLUMN channel")
        connection.exec_driver_sql("INSERT INTO analyticsevent (day, name) VALUES ('2026-10-01', 'catalogue_view')")

    init_database()
    init_database()   # safe to run again: nothing left to add

    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(analyticsevent)")}
        old = connection.exec_driver_sql("SELECT channel FROM analyticsevent").scalar_one()
    assert "channel" in columns and old == "api"


def test_failed_requests_record_nothing(client, db, shop):
    c = shop["customer"]
    assert client.get("/api/bikes/9999", headers=c).status_code == 404
    sunday = {"bike_id": shop["bikes"]["r1"].id, "start_at": "2026-11-08T10:00", "end_at": "2026-11-08T15:00"}
    assert client.post("/api/rentals/quote", json=sunday, headers=c).status_code == 400
    assert events(db) == []


def test_analytics_day_is_the_zurich_date(client, db, shop):
    # 23:30 UTC on Mon 2 Nov is already Tue 3 Nov in Zurich.
    timeutils.freeze_time(datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc))
    client.get("/api/bikes", headers=shop["customer"])
    assert events(db)[0].day == date(2026, 11, 3)


def test_a_failing_analytics_write_does_not_break_the_request(client, db, shop):
    c, bike = shop["customer"], shop["bikes"]["r1"]
    AnalyticsEvent.__table__.drop(db.get_bind())       # the table can't be written
    try:
        assert client.get(f"/api/bikes/{bike.id}", headers=c).status_code == 200
        r = book(client, c, bike.id, f"{SAT}T10:00", f"{SAT}T15:00")
        assert r.status_code == 200, r.text
        assert client.get("/api/rentals", headers=c).json()[0]["id"] == r.json()["id"]   # booking kept
    finally:
        AnalyticsEvent.__table__.create(db.get_bind())


def test_record_never_raises(db, monkeypatch):
    def broken():
        raise RuntimeError("clock is broken")
    monkeypatch.setattr(analytics_service, "today", broken)
    analytics_service.record(db, "catalogue_view")       # no exception
    assert events(db) == []


# ------------------------------------------------------------------ S17: the summary

def at(day: int):
    """Freeze the clock at 12:00 Zurich on `day` November 2026."""
    timeutils.freeze_time(datetime(2026, 11, day, 11, 0, tzinfo=timezone.utc))


def test_summary_over_several_days(client, db, shop):
    r1, r2, s1 = shop["bikes"]["r1"], shop["bikes"]["r2"], shop["bikes"]["s1"]
    extra = make_bike(db, "R-CITY-03", purpose=Purpose.rental)
    record = analytics_service.record

    at(1)                                     # outside a 3-day period ending on the 4th
    record(db, "bike_view", extra.id)
    record(db, "quote", extra.id)
    at(2)
    record(db, "catalogue_view")
    record(db, "bike_view", r1.id)
    record(db, "bike_view", r1.id)
    record(db, "quote", r1.id)
    record(db, "quote", r1.id)
    at(3)
    record(db, "bike_view", r2.id)
    record(db, "bike_view", r1.id)
    record(db, "quote", r2.id)
    record(db, "quote", r1.id)
    record(db, "booking", r1.id)
    record(db, "reservation", s1.id)
    at(4)                                     # today: a day without events

    r = client.get("/staff/analytics?days=3", headers=shop["staff"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["days"], data["since"], data["until"]) == (3, "2026-11-02", "2026-11-04")
    assert [d["day"] for d in data["per_day"]] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    zero = {"catalogue_view": 0, "bike_view": 0, "quote": 0, "booking": 0, "reservation": 0}
    assert data["per_day"][0]["counts"] == {**zero, "catalogue_view": 1, "bike_view": 2, "quote": 2}
    assert data["per_day"][1]["counts"] == {**zero, "bike_view": 2, "quote": 2, "booking": 1, "reservation": 1}
    assert data["per_day"][2]["counts"] == zero
    assert data["totals"] == {"catalogue_view": 1, "bike_view": 4, "quote": 4, "booking": 1, "reservation": 1}
    assert data["top_bikes"] == [
        {"bike_id": r1.id, "code": "R-CITY-01", "name": "Bike R-CITY-01", "views": 3},
        {"bike_id": r2.id, "code": "R-CITY-02", "name": "Bike R-CITY-02", "views": 1},
    ]
    assert data["quote_to_booking_rate"] == 0.25

    # A longer period includes the 1st as well.
    data = client.get("/staff/analytics?days=30", headers=shop["staff"]).json()
    assert len(data["per_day"]) == 30 and data["since"] == "2026-10-06"
    assert data["totals"]["quote"] == 5 and data["quote_to_booking_rate"] == 0.2
    assert [b["bike_id"] for b in data["top_bikes"]] == [r1.id, r2.id, extra.id]   # ties: lower id first


def test_summary_without_events_and_limits(client, shop):
    data = client.get("/staff/analytics", headers=shop["staff"]).json()   # default 30 days
    assert data["days"] == 30 and data["top_bikes"] == [] and data["quote_to_booking_rate"] is None
    assert data["until"] == NOW.date().isoformat()
    assert client.get("/staff/analytics?days=0", headers=shop["staff"]).status_code == 422
    assert client.get("/staff/analytics?days=366", headers=shop["staff"]).status_code == 422
    assert client.get("/staff/analytics?days=365", headers=shop["staff"]).status_code == 200
    assert client.get("/staff/analytics", headers=shop["customer"]).status_code == 403


def test_top_bikes_are_at_most_ten(client, db, shop):
    for n in range(12):
        bike = make_bike(db, f"R-X-{n:02d}")
        for _ in range(n + 1):
            analytics_service.record(db, "bike_view", bike.id)
    top = client.get("/staff/analytics?days=1", headers=shop["staff"]).json()["top_bikes"]
    assert len(top) == 10
    assert [b["views"] for b in top] == list(range(12, 2, -1))
