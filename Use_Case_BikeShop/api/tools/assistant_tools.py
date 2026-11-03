"""
The assistant's tools (SPEC §13): what the AI may ask our code to do.

This file has two parts:

  PART 1: the functions. Plain Python on top of the shop's services. This is
          OUR code, with OUR data and OUR rules. The AI never sees this code.

  PART 2: the tool descriptions. This is the "menu" we send to the AI:
          a name, a plain-English description and the inputs of each tool.
          This is the ONLY thing the AI knows about our tools.

The AI never runs anything itself. It only asks "please run tool X with
these inputs". Our code (scripts/assistant_step3_chat.py) runs it through
run_tool() and sends back the result.

Who the customer is comes from our code, never from the AI: run_tool() gets
the signed-in customer's user_id, and no tool input or output names a person
(SPEC §8.2.6).
"""
from datetime import date as Date, datetime, timedelta

from sqlmodel import Session

from ..config import HOLIDAYS, MAX_DAYS_AHEAD, MIN_RENTAL_HOURS, OPENING_HOURS, SHOP_TZ, TIME_GRID_MINUTES
from ..models.models import Bike, Category
from ..services import analytics_service
from ..services.errors import RuleViolation, ShopError
from ..services.rental_service import WEEKDAYS, RentalService
from ..timeutils import to_local, to_utc, utcnow
from . import demand

rentals = RentalService()
_tickets = []  # staff tickets created while the script runs


def _time(value: str, what: str) -> datetime:
    """'2026-11-07T10:00' (Zurich time) -> aware UTC."""
    try:
        return to_utc(datetime.fromisoformat(str(value)))
    except ValueError:
        raise RuleViolation(f"{what} '{value}' is not a time. Use YYYY-MM-DDTHH:MM, e.g. 2026-11-07T10:00.")


def _date(value: str) -> Date:
    try:
        return Date.fromisoformat(str(value))
    except ValueError:
        raise RuleViolation(f"'{value}' is not a date. Use YYYY-MM-DD, e.g. 2026-11-07.")


def _category(value: str) -> Category:
    try:
        return Category(value)
    except ValueError:
        raise RuleViolation(f"Unknown category '{value}'. Choose one of: {', '.join(c.value for c in Category)}.")


def _local(value: datetime) -> str:
    return to_local(value).isoformat()


def _bike(bike: Bike) -> dict:
    return {"bike_id": bike.id, "code": bike.code, "name": bike.name,
            "category": bike.category.value, "frame_size": bike.frame_size.value}


# =============================================================================
# PART 1: THE FUNCTIONS (normal Python, testable without any AI)
# =============================================================================

# Type 1: LOOK UP  - read our own data
def check_availability(db: Session, start_at: str, end_at: str, category: str | None = None) -> dict:
    """Rental bikes free for the whole period, each with its price."""
    start, end = _time(start_at, "start_at"), _time(end_at, "end_at")
    found = rentals.available_bikes(db, start, end, _category(category) if category else None)
    result = {"start_at": _local(start), "end_at": _local(end), "available": len(found),
              "bikes": [{**_bike(bike), "price_chf": str(price.total_chf)} for bike, _, price in found]}
    if not found:
        result["note"] = "No bike of this kind is free for the whole period. Suggest another time or category."
    return result


# Type 2: COMPUTE  - business rules that must be exactly right every time
def quote_rental(db: Session, bike_id: int, start_at: str, end_at: str) -> dict:
    """Price for renting one bike (SPEC §5.3). Books nothing."""
    start, end = _time(start_at, "start_at"), _time(end_at, "end_at")
    bike, rate, price = rentals.quote(db, int(bike_id), start, end)
    analytics_service.record(db, "quote", bike.id, channel="assistant")   # as the API does (SPEC §5.10)
    return {**_bike(bike), "start_at": _local(start), "end_at": _local(end),
            "billable_hours": price.hours, "full_days": price.full_days, "rest_hours": price.rest_hours,
            "hourly_chf": str(rate.hourly_chf), "daily_chf": str(rate.daily_chf),
            "total_chf": str(price.total_chf), "deposit_chf": str(rate.deposit_chf),
            "note": "Every started hour counts; the daily rate caps each 24 hours. The deposit is paid "
                    "and returned at the counter. This is a quote only: it books nothing and does not "
                    "check availability."}


# Type 3: ACT  - change something (here: a real booking in the database)
def book_rental(db: Session, user_id: str, bike_id: int, start_at: str, end_at: str) -> dict:
    """Book a bike for the signed-in customer. The service checks every rule BEFORE writing."""
    rental = rentals.book(db, user_id, int(bike_id), _time(start_at, "start_at"), _time(end_at, "end_at"))
    analytics_service.record(db, "booking", rental.bike_id, channel="assistant")   # anonymous: no user id
    return {"status": "booked", "rental_id": rental.id, **_bike(db.get(Bike, rental.bike_id)),
            "start_at": _local(rental.start_at), "end_at": _local(rental.end_at),
            "quoted_price_chf": str(rental.quoted_price_chf),
            "next_step": "Pick the bike up at the shop at the start time; pay there."}


# Type 4: HAND OFF  - pass to a human on purpose
def escalate_to_staff(db: Session, reason: str, customer_message: str) -> dict:
    """Create a ticket for a human. In a real shop: send an email or a chat message."""
    _tickets.append(customer_message)
    ticket = f"T-{100 + len(_tickets)}"
    print(f"\n   [STAFF TICKET {ticket}] {reason}: {customer_message}\n")
    return {"status": "forwarded to staff", "ticket_id": ticket,
            "promise_to_customer": "A staff member will answer within one working day."}


# Type 5: PREDICT  - an estimate from a machine-learning model we trained ourselves
def _walk_in_window(day: Date) -> tuple[datetime, datetime]:
    """The part of `day` a walk-in customer could still rent in, as aware UTC."""
    if day in HOLIDAYS:
        raise RuleViolation(f"The shop is closed on {day.day} {day:%b} ({HOLIDAYS[day]}).")
    hours = OPENING_HOURS.get(day.weekday())
    if hours is None:
        raise RuleViolation(f"The shop is closed on {WEEKDAYS[day.weekday()]}s.")
    start = datetime.combine(day, hours[0], SHOP_TZ)
    end = datetime.combine(day, hours[1], SHOP_TZ)
    now = to_local(utcnow())
    if day == now.date():  # today: from the next quarter hour
        next_quarter = (now.replace(second=0, microsecond=0)
                        + timedelta(minutes=TIME_GRID_MINUTES - now.minute % TIME_GRID_MINUTES))
        start = max(start, next_quarter)
        if end - start < timedelta(hours=MIN_RENTAL_HOURS):
            raise RuleViolation("The shop closes soon today, so walking in is no longer possible.")
    return to_utc(start), to_utc(end)


def demand_forecast(db: Session, category: str, date: str) -> dict:
    """Estimate walk-in demand for a day and how likely a walk-in customer still gets a bike."""
    cat, day = _category(category), _date(date)
    today = to_local(utcnow()).date()
    if day < today:
        raise RuleViolation(f"{date} is in the past.")
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise RuleViolation(f"Forecasts go at most {MAX_DAYS_AHEAD} days ahead.")
    start, end = _walk_in_window(day)
    model = demand.load_model()
    if model is None:
        raise RuleViolation("No demand model found. Run `python -m scripts.train_demand_model` first.")

    weather = demand.get_weather_forecast(day)
    expected = demand.expected_demand(model, cat, day, weather["temp_max_c"], weather["rain_mm"])
    free = len(rentals.available_bikes(db, start, end, cat))  # not booked by anyone yet

    # The model predicts an average. Real days scatter around it (Poisson), which gives
    # a likely range and the chance that demand stays below the free bikes.
    low = next(k for k in range(100) if demand.poisson_cdf(k, expected) >= 0.1)
    high = next(k for k in range(100) if demand.poisson_cdf(k, expected) >= 0.9)
    chance = 0 if free <= 0 else round(100 * demand.poisson_cdf(free - 1, expected))
    level, advice = (("fully booked", f"All {cat.value} bikes are already booked that day; walk-in is not possible.")
                     if free <= 0 else
                     ("low", "Walking in on the day should be fine.") if chance >= 85 else
                     ("medium", "Probably fine, but come early in the day.") if chance >= 60 else
                     ("high", "Walk-in is risky; booking is recommended."))

    # Why? Compare with the same day under typical weather for the month (a "what-if").
    reasons = [f"{day:%B} is {demand.SEASON[day.month]}.",
               f"{day:%A}: " + ("Saturdays are busier." if day.weekday() == 5 else "a weekday, usually quieter.")]
    if weather["rain_mm"] is not None:
        typical = demand.expected_demand(model, cat, day, demand.BERN_CLIMATE[day.month][0])
        effect = expected - typical
        reasons.append(f"Weather ({weather['summary']}, {weather['temp_max_c']} C, {weather['rain_mm']} mm rain) "
                       + ("is better than usual for the month, so more demand."
                          if effect > 0.2 else "is worse than usual for the month, so less demand."
                          if effect < -0.2 else "is about normal for the month."))

    return {"category": cat.value, "date": day.isoformat(), "weekday": f"{day:%A}",
            "weather": weather,
            "bikes_not_booked": free,
            "expected_walk_in_rentals": round(expected, 1),
            "likely_range": [low, high],
            "chance_a_bike_is_left_percent": chance,
            "demand_level": level, "walk_in_advice": advice, "reasons": reasons,
            "note": "Estimate from a model trained on made-up past rentals, not a guarantee."}


# =============================================================================
# PART 2: THE TOOL DESCRIPTIONS (the "menu" the AI reads)
# Format: Anthropic / Claude API. Each tool = name + description + input_schema.
# For OpenAI-style AIs (BFH, ChatGPT, Gemini, ...) llm.py rewraps this same menu.
# Tip: the description is a small prompt. Say WHAT it does and WHEN to use it.
# =============================================================================

CATEGORIES = [c.value for c in Category]
TIME = {"type": "string", "description": "Zurich time, format YYYY-MM-DDTHH:MM, on the quarter hour."}

TOOLS = [
    {
        "name": "check_availability",
        "description": "List the rental bikes that are free for a whole period, each with its id and "
                       "price. Use this whenever a customer asks what is available, and before "
                       "quoting or booking. Without a category it lists every kind of bike.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_at": {**TIME, "description": "Pick-up time. " + TIME["description"]},
                "end_at": {**TIME, "description": "Return time. " + TIME["description"]},
                "category": {"type": "string", "enum": CATEGORIES, "description": "Optional kind of bike."},
            },
            "required": ["start_at", "end_at"],
        },
    },
    {
        "name": "quote_rental",
        "description": "Calculate the exact price of renting one bike for a period, with the hourly "
                       "and daily rates and the deposit. Always use this for prices; never calculate "
                       "prices yourself. It books nothing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bike_id": {"type": "integer", "description": "bike_id from check_availability."},
                "start_at": {**TIME, "description": "Pick-up time. " + TIME["description"]},
                "end_at": {**TIME, "description": "Return time. " + TIME["description"]},
            },
            "required": ["bike_id", "start_at", "end_at"],
        },
    },
    {
        "name": "book_rental",
        "description": "Book one bike for the signed-in customer. Only call this AFTER you have "
                       "summarised the booking (bike, times, price) and the customer has explicitly "
                       "confirmed it. For several bikes, call it once per bike.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bike_id": {"type": "integer", "description": "bike_id from check_availability."},
                "start_at": {**TIME, "description": "Pick-up time. " + TIME["description"]},
                "end_at": {**TIME, "description": "Return time. " + TIME["description"]},
            },
            "required": ["bike_id", "start_at", "end_at"],
        },
    },
    {
        "name": "escalate_to_staff",
        "description": "Forward a request to a human staff member. Use for complaints, damage, "
                       "refunds, cancellations, buying a bike, or anything you cannot answer with the "
                       "other tools. Do not guess answers to such questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short reason, e.g. 'complaint'."},
                "customer_message": {"type": "string",
                                     "description": "The customer's request in their words."},
            },
            "required": ["reason", "customer_message"],
        },
    },
    {
        "name": "demand_forecast",
        "description": "Estimate how busy the shop will be on a day and how likely a walk-in "
                       "customer still gets a bike of a category, based on the weather forecast, "
                       "weekday, season and a model trained on past rentals. Use this ONLY when the "
                       "customer does not want to book and would rather come by spontaneously on "
                       "the day. Do not use it for bookings. Present the result as an estimate, "
                       "mention the main reasons (e.g. weather, month, weekday), and never promise "
                       "that a bike will be available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "date": {"type": "string", "description": "Date in format YYYY-MM-DD."},
            },
            "required": ["category", "date"],
        },
    },
]

# Connects the tool NAME the AI asks for to the Python FUNCTION we run.
FUNCTIONS = {
    "check_availability": check_availability,
    "quote_rental": quote_rental,
    "book_rental": book_rental,
    "escalate_to_staff": escalate_to_staff,
    "demand_forecast": demand_forecast,
}
NEEDS_CUSTOMER = {"book_rental"}  # these also get the signed-in customer's user_id, from our code


def run_tool(name: str, inputs: dict, db: Session, user_id: str) -> dict:
    """Run the tool the AI asked for. Errors are returned (not raised),
    so the AI can read them and recover, e.g. offer another time."""
    if name not in FUNCTIONS:
        return {"error": f"Unknown tool '{name}'."}
    try:
        if name in NEEDS_CUSTOMER:
            return FUNCTIONS[name](db, user_id, **inputs)
        return FUNCTIONS[name](db, **inputs)
    except ShopError as e:  # a shop rule said no: the same sentence the API would send
        return {"error": e.message}
    except (TypeError, ValueError) as e:  # wrong or missing inputs
        return {"error": f"Wrong input for {name}: {e}"}


def system_prompt() -> str:
    """The instructions the chat sends with every request (SPEC §13.3)."""
    now = to_local(utcnow())
    hours = "; ".join(f"{WEEKDAYS[d]} {o:%H:%M}-{c:%H:%M}" for d, (o, c) in sorted(OPENING_HOURS.items()))
    return f"""You are the friendly assistant of BikeShop, a bike shop in Bern that rents and sells bikes.
Now is {now:%A, %Y-%m-%d %H:%M} (Zurich time).
Opening hours: {hours}. Closed on Sundays and public holidays.
Pick-up and return must be within opening hours, on the quarter hour.
Use the tools for availability, prices and bookings. Never invent bikes, prices or times.
Before booking, summarise the booking and ask the customer to confirm.
The customer is already signed in. Never ask for names, email addresses or other personal data.
Keep answers short."""
