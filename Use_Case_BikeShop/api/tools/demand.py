"""
The demand model behind the demand_forecast tool (SPEC §13.5).

Used by the tool AND by scripts/train_demand_model.py, so the model sees
exactly the same features when it is trained and when it predicts.
"""
import math
import pickle
from datetime import date

import httpx

from ..config import DATA_DIR
from ..models.models import Category

MODEL_FILE = DATA_DIR / "demand_model.pkl"        # created by scripts/train_demand_model.py
HISTORY_FILE = DATA_DIR / "rental_history.csv"    # the made-up history it was trained on

BERN = {"latitude": 46.95, "longitude": 7.45}

# Typical weather in Bern per month: average max temperature (C), chance of a rainy day
BERN_CLIMATE = {1: (3, 0.40), 2: (5, 0.38), 3: (10, 0.42), 4: (14, 0.45),
                5: (19, 0.50), 6: (22, 0.48), 7: (24, 0.42), 8: (24, 0.42),
                9: (19, 0.38), 10: (14, 0.40), 11: (8, 0.42), 12: (4, 0.42)}
TYPICAL_RAIN_MM = 6  # how much it rains on a typical rainy day
SEASON = {**dict.fromkeys([11, 12, 1, 2, 3], "low season"),
          **dict.fromkeys([4, 10], "shoulder season"),
          **dict.fromkeys([5, 6, 7, 8, 9], "high season")}


def make_features(category: Category, day: date, temp_max_c: float, rain_mm: float) -> list:
    """Turn one (category, day, weather) into the numbers the model learns from."""
    return [*(1 if category == c else 0 for c in Category),  # one-hot category
            day.weekday(),                                   # 0 = Monday
            1 if day.weekday() == 5 else 0,                  # Saturday (Sundays are closed)
            day.month,
            temp_max_c,
            rain_mm]


def get_weather_forecast(day: date) -> dict:
    """Weather for Bern from Open-Meteo (free, no key). Falls back to the
    typical weather for the month if the date is too far ahead or offline."""
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=5, params={
            **BERN, "timezone": "Europe/Zurich",
            "start_date": day.isoformat(), "end_date": day.isoformat(),
            "daily": "temperature_2m_max,precipitation_sum,precipitation_probability_max,weather_code"})
        r.raise_for_status()
        d = r.json()["daily"]
        code = d["weather_code"][0]
        summary = ("sunny" if code == 0 else "partly cloudy" if code <= 3 else
                   "foggy" if code <= 48 else "snow" if 71 <= code <= 77 else
                   "thunderstorms" if code >= 95 else "rain")
        return {"source": "Open-Meteo forecast", "summary": summary,
                "temp_max_c": round(d["temperature_2m_max"][0]),
                "rain_mm": round(d["precipitation_sum"][0], 1),
                "rain_probability_percent": d["precipitation_probability_max"][0]}
    except Exception:  # more than ~16 days ahead, no internet, API down ...
        temp, rain_chance = BERN_CLIMATE[day.month]
        return {"source": "typical weather for the month (no forecast available for this date)",
                "summary": "unknown", "temp_max_c": temp, "rain_mm": None,
                "rain_probability_percent": round(rain_chance * 100)}


def load_model():
    """The trained model, or None if the training script hasn't run yet."""
    if not MODEL_FILE.exists():
        return None
    with open(MODEL_FILE, "rb") as f:
        return pickle.load(f)


def expected_demand(model, category: Category, day: date, temp_max_c: float, rain_mm: float | None = None) -> float:
    """Model prediction. If rain is unknown, average a dry and a rainy day by the month's rain chance."""
    if rain_mm is not None:
        return float(model.predict([make_features(category, day, temp_max_c, rain_mm)])[0])
    rain_chance = BERN_CLIMATE[day.month][1]
    dry, wet = model.predict([make_features(category, day, temp_max_c, 0),
                              make_features(category, day, temp_max_c, TYPICAL_RAIN_MM)])
    return float((1 - rain_chance) * dry + rain_chance * wet)


def poisson_cdf(k: int, mean: float) -> float:
    """P(X <= k) for a Poisson-distributed count with this mean."""
    return sum(math.exp(-mean) * mean ** i / math.factorial(i) for i in range(k + 1))
