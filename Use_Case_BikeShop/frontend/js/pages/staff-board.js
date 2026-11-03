/*
  Staff: today's board (#/staff/board). What has to happen at the counter.

  - Pick-ups due: booked rentals that start on the chosen day.
  - Returns due: active rentals that end on the chosen day.
  - Overdue: active rentals past their return time (any day).
  - At risk: bookings for a bike that staff have put into maintenance.

  Data: GET /staff/rentals?date=YYYY-MM-DD (rentals starting or ending that
  day, Zurich time), GET /staff/rentals?overdue=true and GET /staff/inventory.
  Buttons: Pick up, Return (shows the final price) and Cancel.
  /staff calls are free and not rate limited.
*/

import * as api from "../api.js";
import { el, show, stat, loading, errorBox, message, run, fmtChf, fmtTime, fmtDay, shopToday } from "../ui.js";

let chosenDay = null;   // remembered while the tab is open

export async function render(view, { flash }) {
  chosenDay = chosenDay || shopToday();
  const notice = el("div", {}, flash);
  const board = el("div", {}, loading());
  const dayInput = el("input", { type: "date", value: chosenDay });
  dayInput.addEventListener("change", () => { chosenDay = dayInput.value || shopToday(); load(); });

  show(view,
    el("h1", {}, "Today's board"),
    el("div", { class: "form-grid" }, el("label", {}, "Day", dayInput)),
    notice,
    board);

  /** Run a staff action on a rental, show the outcome and reload the board. */
  async function act(button, action, rental, describe) {
    const result = await run(button, notice, () => action(rental.id));
    if (result) {
      show(notice, message("success", describe(result)));
      load();
    }
  }

  function rentalCard(rental) {
    const buttons = [];
    if (rental.status === "booked") {
      const pickup = el("button", { type: "button", class: "primary" }, "Pick up");
      pickup.addEventListener("click", () => act(pickup, api.pickupRental, rental,
        (r) => `${r.bike_name} handed over to ${r.username || "the customer"}.`));
      const cancel = el("button", { type: "button", class: "danger" }, "Cancel");
      cancel.addEventListener("click", () => act(cancel, api.staffCancelRental, rental,
        (r) => `Booking of ${r.bike_name} cancelled.`));
      buttons.push(pickup, cancel);
    } else if (rental.status === "active") {
      const giveBack = el("button", { type: "button", class: "primary" }, "Return");
      giveBack.addEventListener("click", () => act(giveBack, api.returnRental, rental,
        (r) => `${r.bike_name} returned. Final price: ${fmtChf(r.final_price_chf)} (quoted ${fmtChf(r.quoted_price_chf)}).`));
      buttons.push(giveBack);
    }
    return el("div", { class: "card row" },
      el("div", { class: "grow" },
        el("h3", {}, `${rental.bike_name} (${rental.bike_code})`),
        el("div", {}, `${rental.username || rental.user_id} · ${fmtTime(rental.start_at)} → ${fmtTime(rental.end_at)}`),
        el("div", { class: "small" },
          el("span", { class: "badge" }, rental.status), ` quoted ${fmtChf(rental.quoted_price_chf)} `,
          rental.overdue ? el("span", { class: "badge warn" }, "overdue") : null, " ",
          rental.at_risk ? el("span", { class: "badge warn" }, "at risk: bike in maintenance") : null)),
      el("div", { class: "buttons" }, buttons));
  }

  async function load() {
    const day = chosenDay;
    let onDay, overdue, summary;
    try {
      [onDay, overdue, summary] = await Promise.all([
        api.staffRentals({ date: day }), api.staffRentals({ overdue: true }), api.inventorySummary()]);
    } catch (error) {
      show(board, errorBox(error));
      return;
    }
    const sameDay = (iso) => iso.slice(0, 10) === day;   // API times are in Zurich time
    const pickups = onDay.filter((r) => r.status === "booked" && sameDay(r.start_at));
    const returns = onDay.filter((r) => r.status === "active" && sameDay(r.end_at) && !r.overdue);
    const atRisk = summary.at_risk_bookings;
    const finished = onDay.filter((r) => r.status === "returned" || r.status === "cancelled");

    const section = (heading, rentals, emptyText) => [
      el("h2", {}, `${heading} (${rentals.length})`),
      rentals.length ? rentals.map(rentalCard) : el("p", { class: "muted" }, emptyText),
    ];
    show(board,
      el("div", { class: "stats" },
        stat("Pick-ups due", pickups.length), stat("Returns due", returns.length),
        stat("Overdue", overdue.length), stat("At risk", atRisk.length)),
      section(`Pick-ups due ${fmtDay(day)}`, pickups, "No pick-ups due."),
      section(`Returns due ${fmtDay(day)}`, returns, "No returns due."),
      section("Overdue", overdue, "Nothing overdue."),
      section("At-risk bookings (bike in maintenance)", atRisk, "No bookings at risk."),
      finished.length ? el("details", {},
        el("summary", {}, `Finished on this day (${finished.length})`),
        finished.map((r) => el("p", {},
          `${r.bike_name} (${r.bike_code}) · ${r.username || r.user_id} · ${r.status}`
          + (r.final_price_chf ? ` · final ${fmtChf(r.final_price_chf)}` : "")))) : null);
  }

  await load();
}
