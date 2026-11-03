/*
  Staff: analytics (#/staff/analytics). How the shop is used, anonymously.

  The API records one event per catalogue search, bike view, quote, booking
  and reservation: only the day, the event and the bike, never who it was
  (SPEC §5.10). This page shows, for the chosen period:
  - totals per event and the quote → booking rate;
  - the 10 most-viewed bikes, as bars;
  - a table of the counts per day.

  Data: GET /staff/analytics?days=30. /staff calls are free.
*/

import * as api from "../api.js";
import { el, show, table, stat, select, loading, errorBox, message, fmtDay, fmtNumber } from "../ui.js";

// The events in funnel order, with their label on this page.
const EVENTS = [
  ["catalogue_view", "Catalogue"],
  ["bike_view", "Bike views"],
  ["quote", "Quotes"],
  ["booking", "Bookings"],
  ["reservation", "Reservations"],
];
const PERIODS = [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"], [365, "Last 365 days"]];

let chosenDays = 30;   // remembered while the tab is open

/** 0.25 -> "25 %"; null (no quotes yet) -> "–" */
const fmtRate = (rate) => (rate === null ? "–" : `${Math.round(rate * 100)} %`);

/** Horizontal bars: one row per item, the bar's length relative to the largest value. */
function barChart(items) {
  const largest = Math.max(...items.map((item) => item.value), 1);
  return el("div", { class: "bars" }, items.map((item) => {
    const bar = el("div", { class: "bar" });
    bar.style.width = `${(item.value / largest) * 100}%`;   // a number we computed, not API text
    return [item.label, el("div", { class: "bar-track", "aria-hidden": "true" }, bar), fmtNumber(item.value)];
  }));
}

export async function render(view) {
  const periodSelect = select(PERIODS, chosenDays, { name: "days" });
  const content = el("div", {}, loading());
  periodSelect.addEventListener("change", () => { chosenDays = Number(periodSelect.value); load(); });

  show(view,
    el("h1", {}, "Analytics"),
    el("p", { class: "muted" },
      "Anonymous: the shop records what happened, on which day and with which bike, but not who it was."),
    el("div", { class: "form-grid" }, el("label", {}, "Period", periodSelect)),
    content);

  async function load() {
    show(content, loading());
    let data;
    try {
      data = await api.getAnalytics(chosenDays);
    } catch (error) {
      show(content, errorBox(error));
      return;
    }

    // Days with at least one event, newest first.
    const activeDays = data.per_day
      .filter((d) => EVENTS.some(([name]) => d.counts[name] > 0))
      .reverse();

    show(content,
      el("p", { class: "small muted" }, `${fmtDay(data.since)} to ${fmtDay(data.until)} (shop time)`),
      el("div", { class: "stats" },
        EVENTS.map(([name, label]) => stat(label, fmtNumber(data.totals[name] || 0))),
        stat("Quote → booking", fmtRate(data.quote_to_booking_rate))),
      el("p", { class: "legend" },
        "Quote → booking: bookings divided by quotes. The bike page asks for a new quote each time "
        + "the customer changes the times, so a low rate is normal."),

      el("h2", {}, "Most-viewed bikes"),
      data.top_bikes.length === 0
        ? el("p", { class: "muted" }, "No bike was viewed in this period.")
        : barChart(data.top_bikes.map((b) => ({
          label: b.code
            ? el("a", { href: `#/bike/${b.bike_id}` }, `${b.name} (${b.code})`)
            : `Bike ${b.bike_id} (deleted)`,
          value: b.views,
        }))),

      el("h2", {}, "Per day"),
      activeDays.length === 0
        ? el("p", { class: "muted" }, "No events in this period yet.")
        : [
          table([
            { label: "Day", value: (d) => fmtDay(d.day) },
            ...EVENTS.map(([name, label]) => ({ label, num: true, value: (d) => fmtNumber(d.counts[name]) })),
          ], activeDays),
          el("p", { class: "legend" }, "Days without any events are left out."),
        ]);
  }

  await load();
}
