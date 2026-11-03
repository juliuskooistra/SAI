"""
TRAIN the model behind the demand_forecast tool (SPEC §13.5). Run this once.

    python -m scripts.train_demand_model

A "predict" tool has two halves:

  1. TRAINING (this file, offline): learn from past data, save the model to a file.
  2. PREDICTING (demand_forecast in api/tools/assistant_tools.py): load the
     file, make one prediction.

We don't have years of walk-in rentals, so we first MAKE UP two years of
history with patterns we choose (Saturdays busier, rain kills demand, summer
is high season ...). Then we train a model on it and check whether it learned
those patterns. A real shop would skip part A and load its own Rental table.
"""
import csv
import pickle
import random
from datetime import date, timedelta

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from api.config import DATA_DIR
from api.models.models import Category
from api.tools.demand import BERN_CLIMATE, HISTORY_FILE, MODEL_FILE, TYPICAL_RAIN_MM, make_features

# =============================================================================
# PART A: invent the history (the "true" patterns the model should discover)
# =============================================================================

# Walk-in rentals on an average day, per category
BASE_RENTALS = {Category.city: 3.0, Category.ebike: 2.5, Category.mountain: 1.2, Category.road: 1.0,
                Category.gravel: 0.8, Category.kids: 0.6, Category.cargo: 0.5}
SEASON_FACTOR = {1: .35, 2: .4, 3: .6, 4: .85, 5: 1.1, 6: 1.3,
                 7: 1.4, 8: 1.35, 9: 1.1, 10: .8, 11: .45, 12: .35}
SATURDAY_FACTOR = {Category.city: 1.5, Category.ebike: 1.6, Category.mountain: 1.8, Category.road: 1.7,
                   Category.gravel: 1.7, Category.kids: 2.2, Category.cargo: 1.8}


def poisson(rng: random.Random, mean: float) -> int:
    """Random count of rentals with this average (Knuth's method)."""
    limit, k, p = 2.718281828 ** -mean, 0, 1.0
    while True:
        p *= rng.random()
        if p < limit:
            return k
        k += 1


def true_demand(rng, category, day, temp, rain_mm):
    mean = BASE_RENTALS[category] * SEASON_FACTOR[day.month]
    if day.weekday() == 5:
        mean *= SATURDAY_FACTOR[category]
    mean *= min(max(1 + 0.03 * (temp - 15), 0.5), 1.35)  # warmer is better ...
    if temp > 30:
        mean *= 0.8                                        # ... until it is too hot
    if rain_mm > 8:
        mean *= 0.3                                        # heavy rain
    elif rain_mm > 1:
        mean *= 0.55                                       # some rain
    return poisson(rng, mean)


def make_history(first: date, last: date, seed: int = 42) -> list[dict]:
    """One row per open day (Mon-Sat) and category, with made-up weather and rentals."""
    rng = random.Random(seed)
    rows, day = [], first
    while day <= last:
        if day.weekday() != 6:  # closed on Sundays
            normal_temp, rain_chance = BERN_CLIMATE[day.month]
            temp = round(rng.gauss(normal_temp, 4))
            rain = round(rng.expovariate(1 / TYPICAL_RAIN_MM), 1) if rng.random() < rain_chance else 0.0
            for category in Category:
                rows.append({"date": day.isoformat(), "category": category.value, "temp_max_c": temp,
                             "rain_mm": rain, "rentals": true_demand(rng, category, day, temp, rain)})
        day += timedelta(days=1)
    return rows


# =============================================================================
# PART B: train the model
# =============================================================================

def features(rows):
    return [make_features(Category(r["category"]), date.fromisoformat(r["date"]), r["temp_max_c"], r["rain_mm"])
            for r in rows]


def train(rows) -> HistGradientBoostingRegressor:
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05,
                                          random_state=0)  # "poisson": we predict counts
    return model.fit(features(rows), [r["rentals"] for r in rows])


def main() -> None:
    rows = make_history(date(2024, 11, 1), date(2026, 10, 31))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(f"A) Made up {len(rows)} rows of rental history -> {HISTORY_FILE} (open it!)")

    # Train on the first ~21 months, test on the last 3 months the model has never seen.
    split = next(i for i, r in enumerate(rows) if r["date"] >= "2026-08-01")
    train_rows, test_rows = rows[:split], rows[split:]
    model = train(train_rows)
    y_test = [r["rentals"] for r in test_rows]

    # Is it any good? Compare with a naive guess: "the average for that category".
    averages = {c.value: sum(r["rentals"] for r in train_rows if r["category"] == c.value) /
                sum(1 for r in train_rows if r["category"] == c.value) for c in Category}
    naive = [averages[r["category"]] for r in test_rows]
    print("\nB) Test on Aug-Oct 2026 (data the model has never seen):")
    print(f"   naive guess (average per category) is off by {mean_absolute_error(y_test, naive):.2f} rentals/day")
    print(f"   our model                          is off by "
          f"{mean_absolute_error(y_test, model.predict(features(test_rows))):.2f} rentals/day")

    # Did it learn the patterns we hid in the data?
    print("\nC) What did the model learn? Expected e-bike walk-in rentals:")
    for label, d, temp, rain in [
            ("sunny Saturday in July, 26 C  ", date(2026, 7, 11), 26, 0),
            ("rainy Saturday in July, 18 C  ", date(2026, 7, 11), 18, 10),
            ("dry Tuesday in November, 9 C  ", date(2026, 11, 10), 9, 0),
            ("rainy Tuesday in November, 6 C", date(2026, 11, 10), 6, 7)]:
        print(f"   {label}: {model.predict([make_features(Category.ebike, d, temp, rain)])[0]:.1f}")

    # Retrain on ALL data for the final model, then save it to a file.
    model = train(rows)
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(model, f)
    print(f"\nD) Model saved to {MODEL_FILE}. The demand_forecast tool loads it from there.")


if __name__ == "__main__":
    main()
