"""S13 assistant tools (SPEC §11, §13). No AI and no network: the AI is faked, the weather mocked."""
import json
import pickle
from datetime import date, datetime

import httpx
import openai
import pytest
from sqlmodel import select

from api.models.models import Rental, User
from api.services.pricing_service import rental_price
from api.timeutils import to_utc
from api.tools import demand
from api.tools.brankas_great_tools import TOOLS, run_tool
from api.tools.llm import BUSY_MESSAGE, AIError, Busy, OpenAIChat, Reply, ToolCall, openai_tools
from scripts.assistant_step3_chat import chat_turn
from scripts.train_demand_model import make_history, train

from .conftest import SAT, SUN, make_user


@pytest.fixture
def carla(db, shop):
    """The signed-in customer's user_id (the fixture `shop` creates carla)."""
    return db.exec(select(User).where(User.username == "carla")).first().user_id


def period(day=SAT, start="10:00", end="14:00"):
    return {"start_at": f"{day}T{start}", "end_at": f"{day}T{end}"}


# ---------------------------------------------------------------- the tools

def test_availability_lists_free_bikes_with_price(db, shop, carla):
    r = run_tool("check_availability", {**period(), "category": "city"}, db, carla)
    assert [b["code"] for b in r["bikes"]] == ["R-CITY-01", "R-CITY-02"]
    assert {b["price_chf"] for b in r["bikes"]} == {"32.00"}   # 4 h x 8
    assert r["start_at"] == f"{SAT}T10:00:00+01:00"

    run_tool("book_rental", {"bike_id": shop["bikes"]["r1"].id, **period()}, db, carla)
    r = run_tool("check_availability", period(), db, carla)
    assert [b["code"] for b in r["bikes"]] == ["R-CITY-02"]


@pytest.mark.parametrize("name, inputs", [
    ("check_availability", period(SUN)),
    ("quote_rental", {"bike_id": 1, **period(SUN)}),
    ("book_rental", {"bike_id": 1, **period(SUN)}),
    ("demand_forecast", {"category": "city", "date": SUN}),
])
def test_sunday_is_an_error_not_an_exception(db, shop, carla, name, inputs):
    r = run_tool(name, inputs, db, carla)
    assert r["error"].startswith("The shop is closed on Sundays")
    assert db.exec(select(Rental)).all() == []


def test_quote_matches_pricing_service(db, shop, carla):
    inputs = {"bike_id": shop["bikes"]["r1"].id, "start_at": f"{SAT}T10:00", "end_at": "2026-11-09T12:00"}
    r = run_tool("quote_rental", inputs, db, carla)
    expected = rental_price(to_utc(datetime.fromisoformat(inputs["start_at"])),
                            to_utc(datetime.fromisoformat(inputs["end_at"])), 8, 35)
    assert r["total_chf"] == str(expected.total_chf) == "86.00"   # 50 h = 2 days + 2 h
    assert r["deposit_chf"] == "100.00"


def test_booking_belongs_to_the_signed_in_customer_and_names_nobody(db, shop, carla):
    r = run_tool("book_rental", {"bike_id": shop["bikes"]["r1"].id, **period()}, db, carla)
    assert r["status"] == "booked"
    assert db.get(Rental, r["rental_id"]).user_id == carla
    text = json.dumps(r)
    assert carla not in text and "carla" not in text and "@" not in text


def test_booking_limit_comes_back_as_error(db, shop, carla):
    r1, r2 = shop["bikes"]["r1"].id, shop["bikes"]["r2"].id
    for bike, times in [(r1, ("10:00", "11:00")), (r2, ("10:00", "11:00")), (r1, ("12:00", "13:00"))]:
        assert run_tool("book_rental", {"bike_id": bike, **period(SAT, *times)}, db, carla)["status"] == "booked"
    r = run_tool("book_rental", {"bike_id": r2, **period(SAT, "12:00", "13:00")}, db, carla)
    assert "limit is 3" in r["error"]


def test_the_ai_cannot_choose_the_customer(db, shop, carla):
    other = make_user(db, "olga").user_id
    r = run_tool("book_rental", {"bike_id": shop["bikes"]["r1"].id, **period(), "user_id": other}, db, carla)
    assert "error" in r
    assert db.exec(select(Rental)).all() == []


@pytest.mark.parametrize("name, inputs, expected", [
    ("drop_database", {}, "Unknown tool"),
    ("quote_rental", {"bike_id": 1}, "Wrong input"),
    ("quote_rental", {"bike_id": "abc", **period()}, "Wrong input"),
    ("check_availability", {"start_at": "next Saturday", "end_at": f"{SAT}T14:00"}, "is not a time"),
    ("check_availability", {**period(), "category": "tandem"}, "Unknown category"),
])
def test_bad_requests_are_errors_not_exceptions(db, shop, carla, name, inputs, expected):
    assert expected in run_tool(name, inputs, db, carla)["error"]


# ---------------------------------------------------------------- the menu

def test_menu_asks_for_nobody_and_describes_every_tool():
    for tool in TOOLS:
        assert len(tool["description"]) > 40
        for prop in tool["input_schema"]["properties"]:
            assert not any(word in prop for word in ("name", "email", "user", "person", "customer_id"))
    converted = openai_tools(TOOLS)
    assert [t["function"]["name"] for t in converted] == [t["name"] for t in TOOLS]
    assert [t["function"]["parameters"] for t in converted] == [t["input_schema"] for t in TOOLS]


# ---------------------------------------------------------------- the chat loop

class FakeAI:
    """Answers with the scripted replies, in order; records what it was sent."""

    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def ask(self, messages):
        self.sent.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def assistant_message(self, reply):
        return [{"role": "assistant", "content": reply.text, "calls": [c.name for c in reply.tool_calls]}]

    def tool_result_messages(self, tool_calls, results):
        return [{"role": "tool", "id": c.id, "content": r} for c, r in zip(tool_calls, results)]


def test_chat_runs_the_tool_and_returns_the_answer(db, shop, carla):
    ai = FakeAI(Reply("", [ToolCall("t1", "check_availability", {**period(), "category": "city"})]),
                Reply("Two city bikes are free, CHF 32 each."))
    messages = [{"role": "user", "content": "City bike Saturday 10-14?"}]
    shown = []
    answer = chat_turn(ai, messages, db, carla, show=shown.append)
    assert answer == "Two city bikes are free, CHF 32 each."
    assert ai.sent[1][-1]["content"]["available"] == 2          # the result went back to the AI
    assert shown[0].startswith("   [TOOL CALL] check_availability")
    assert messages[-1]["content"] == answer


def test_busy_keeps_the_conversation(db, shop, carla):
    messages = [{"role": "user", "content": "Hello"}]
    assert chat_turn(FakeAI(Busy()), messages, db, carla) == BUSY_MESSAGE
    assert messages == [{"role": "user", "content": "Hello"}]


REQUEST = httpx.Request("POST", "https://inference.test/v1/chat/completions")


@pytest.mark.parametrize("error, expected", [
    (openai.RateLimitError("slow down", body=None, response=httpx.Response(429, request=REQUEST)), BUSY_MESSAGE),
    (openai.AuthenticationError("bad key", body=None, response=httpx.Response(401, request=REQUEST)), "refused the key"),
    (openai.NotFoundError("no model", body=None, response=httpx.Response(404, request=REQUEST)), "doesn't know the model"),
    (openai.APIConnectionError(request=REQUEST), "Can't reach the AI service"),
])
def test_ai_service_errors_become_sentences(error, expected):
    class Completions:
        def create(self, **_):
            raise error

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    with pytest.raises(AIError, match=expected):
        OpenAIChat(client, "gpt-oss:120b", "system", TOOLS).ask([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------- demand_forecast

@pytest.fixture(scope="module")
def small_model():
    return train(make_history(date(2025, 11, 1), date(2026, 10, 31)))


@pytest.fixture
def model_file(tmp_path, monkeypatch, small_model):
    path = tmp_path / "demand_model.pkl"
    path.write_bytes(pickle.dumps(small_model))
    monkeypatch.setattr(demand, "MODEL_FILE", path)
    monkeypatch.setattr(demand, "get_weather_forecast", lambda day: {
        "source": "test", "summary": "sunny", "temp_max_c": 14, "rain_mm": 0.0, "rain_probability_percent": 5})
    return path


def test_forecast_gives_estimate_and_reasons(db, shop, carla, model_file):
    r = run_tool("demand_forecast", {"category": "city", "date": SAT}, db, carla)
    assert r["bikes_not_booked"] == 2
    assert r["expected_walk_in_rentals"] > 0
    low, high = r["likely_range"]
    assert low <= high
    assert 0 < r["chance_a_bike_is_left_percent"] <= 100
    assert any("Saturdays are busier" in reason for reason in r["reasons"])
    assert "estimate" in r["note"].lower()


def test_forecast_when_every_bike_is_booked(db, shop, carla, model_file):
    for bike in ("r1", "r2"):
        run_tool("book_rental", {"bike_id": shop["bikes"][bike].id, **period(SAT, "09:00", "16:00")}, db, carla)
    r = run_tool("demand_forecast", {"category": "city", "date": SAT}, db, carla)
    assert r["chance_a_bike_is_left_percent"] == 0
    assert r["demand_level"] == "fully booked"


def test_forecast_without_model_says_how_to_train(db, shop, carla, tmp_path, monkeypatch):
    monkeypatch.setattr(demand, "MODEL_FILE", tmp_path / "missing.pkl")
    r = run_tool("demand_forecast", {"category": "city", "date": SAT}, db, carla)
    assert "python -m scripts.train_demand_model" in r["error"]


def test_forecast_rejects_the_past(db, shop, carla, model_file):
    assert "in the past" in run_tool("demand_forecast", {"category": "city", "date": "2026-10-31"}, db, carla)["error"]
