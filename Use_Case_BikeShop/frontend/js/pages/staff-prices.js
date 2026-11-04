/*
  Staff: the rental price list (#/staff/prices), one row per bike category.

  Reads GET /api/rental-rates and saves one category with
  PUT /staff/rental-rates/{category}. A rental costs the hourly rate per
  started hour, capped at the daily rate for every 24 hours. Existing bookings
  keep the price they were quoted; new quotes use the new rates at once.
*/

import * as api from "../api.js";
import { el, show, table, loading, errorBox, message, run, fmtChf, CATEGORIES } from "../ui.js";

export async function render(view, { flash }) {
  const notice = el("div", {}, flash);
  const content = el("div", {}, loading());
  show(view,
    el("h1", {}, "Price list"),
    el("p", {}, "Rental price per started hour, capped at the daily rate for every 24 hours. "
      + "Changes apply to new quotes and bookings; existing bookings keep their price."),
    notice,
    content);

  let rates;
  try {
    rates = await api.rentalRates();
  } catch (error) {
    show(content, errorBox(error));
    return;
  }
  const rateOf = Object.fromEntries(rates.map((rate) => [rate.category, rate]));

  // One row per category: three number inputs and a Save button.
  const moneyInput = (value, label) =>
    el("input", { type: "number", min: 0, step: "0.05", value: value ?? "", "aria-label": label, required: true });

  const rows = CATEGORIES.map((category) => {
    const rate = rateOf[category];
    const hourly = moneyInput(rate?.hourly_chf, `${category} per hour`);
    const daily = moneyInput(rate?.daily_chf, `${category} per day`);
    const deposit = moneyInput(rate?.deposit_chf, `${category} deposit cap`);
    const save = el("button", { type: "button", class: "primary" }, "Save");
    save.addEventListener("click", async () => {
      if ([hourly, daily, deposit].some((input) => input.value === "")) {
        show(notice, message("error", `Please fill in all three prices for ${category}.`));
        return;
      }
      const saved = await run(save, notice, () => api.setRentalRate(category, {
        hourly_chf: hourly.value, daily_chf: daily.value, deposit_chf: deposit.value,
      }));
      if (saved) {
        show(notice, message("success", `Saved ${category}: ${fmtChf(saved.hourly_chf)}/h, `
          + `${fmtChf(saved.daily_chf)}/day, deposit at most ${fmtChf(saved.deposit_chf)}.`));
      }
    });
    return { category: rate ? category : `${category} (no price yet)`, hourly, daily, deposit, save };
  });

  show(content, table([
    { label: "Category", value: (r) => r.category },
    { label: "Per hour (CHF)", value: (r) => r.hourly },
    { label: "Per day (CHF)", value: (r) => r.daily },
    { label: "Deposit cap (CHF)", value: (r) => r.deposit },   // deposit = 2 x price, at most this
    { label: "", value: (r) => r.save },
  ], rows));
}
