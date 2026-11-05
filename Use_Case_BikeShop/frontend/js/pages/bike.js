/*
  Bike detail (#/bike/<id>): rent a rental bike or reserve a bike for sale.

  - Rental bike: the rate, then pick-up and return inputs on the 15-minute
    grid. Every change asks for a quote (POST /api/rentals/quote, 1 token),
    shortly after you stop changing things. "Book" books it (POST /api/rentals).
  - Sale bike: the price and "Reserve" (POST /api/orders). The shop then holds
    the bike for you until a date the API sets; you pay and collect in the shop.

  A period chosen on the catalogue's availability check arrives in the
  address: #/bike/5?start=2026-11-07T10:00…&end=…
*/

import * as api from "../api.js";
import { el, show, loading, errorBox, message, run, setFlash, periodPicker, fmtChf, fmtTime, fmtDay, bikeTitle } from "../ui.js";

export async function render(view, { id, query }) {
  show(view, el("p", {}, el("a", { href: "#/catalogue" }, "← Back to the catalogue")), loading());

  const bikeId = Number(id);
  if (!Number.isInteger(bikeId)) {
    show(view, el("h1", {}, "Bike details"), message("info", "Pick a bike in the catalogue first."));
    return;
  }

  let bike;
  try {
    bike = await api.getBike(bikeId);
  } catch (error) {
    view.lastChild.replaceWith(errorBox(error));
    return;
  }

  const action = el("div", {});
  view.lastChild.replaceWith(
    el("h1", {}, bikeTitle(bike)),
    el("p", {}, bike.description),
    el("p", { class: "muted" },
      `${bike.category} · frame ${bike.frame_size} · ${bike.color} · ${bike.year} · ${bike.condition} · status: ${bike.status}`),
    action);

  if (bike.purpose === "sale") drawReserve(action, bike);
  else await drawRent(action, bike, query);
}

// ---- sale bike: reserve -------------------------------------------------------

function drawReserve(area, bike) {
  const result = el("div", {});
  const reserveButton = el("button", { type: "button", class: "primary" }, "Reserve");
  reserveButton.addEventListener("click", async () => {
    const order = await run(reserveButton, result, () => api.reserveBike(bike.id));
    if (order) {
      reserveButton.hidden = true;
      show(result, message("success",
        `Reserved! We hold ${order.bike_name} for you until ${fmtTime(order.expires_at)}. Pay and collect it in the shop.`,
        el("a", { href: "#/my" }, "See my orders")));
    }
  });

  show(area,
    el("h2", {}, `Price: ${fmtChf(bike.sale_price_chf)}`),
    bike.status === "available"
      ? [el("p", {}, "Reserve the bike and we hold it for you. Pay and collect it in the shop."),
        el("div", { class: "buttons" }, reserveButton)]
      : message("warning", `This bike is ${bike.status} and cannot be reserved right now.`),
    result);
}

// ---- rental bike: quote and book ------------------------------------------------

async function drawRent(area, bike, query) {
  const rate = bike.rental_rate;
  const quoteArea = el("div", { "aria-live": "polite" });
  const bookButton = el("button", { type: "button", class: "primary", disabled: true }, "Book");
  const bookErrors = el("div", {});

  show(area,
    rate ? [
      el("h2", {}, `${fmtChf(rate.hourly_chf)} per hour, at most ${fmtChf(rate.daily_chf)} per day`),
      el("p", { class: "muted small" }, `Deposit at pick-up: twice the rental price, at most ${fmtChf(rate.deposit_chf)}, paid back on return.`),
    ] : message("warning", "There is no price for this kind of bike yet."),
    bike.status !== "available"
      ? message("warning", `This bike is in ${bike.status} and cannot be booked right now.`
        + (bike.ready_estimate ? ` We expect it back on ${fmtDay(bike.ready_estimate)}; that is an estimate.` : "")) : null,
    el("h2", {}, "When do you need it?"),
    el("div", { id: "picker" }, loading()),
    quoteArea,
    el("div", { class: "buttons" }, bookButton),
    bookErrors);

  let hours;
  try {
    hours = await api.openingHours();
  } catch (error) {
    show(area.querySelector("#picker"), errorBox(error));
    return;
  }

  // Ask for a quote shortly after the last change (saves tokens while clicking).
  let period = { startAt: null, endAt: null };
  let timer = null;
  let asked = 0;   // so a slow old answer can't overwrite a newer one
  function periodChanged(newPeriod) {
    period = newPeriod;
    bookButton.disabled = true;
    clearTimeout(timer);
    if (!period.startAt) { quoteArea.replaceChildren(); return; }
    show(quoteArea, el("p", { class: "loading" }, "Getting a price…"));
    timer = setTimeout(getQuote, 400);
  }

  async function getQuote() {
    const myTurn = ++asked;
    try {
      const quote = await api.quoteRental(bike.id, period.startAt, period.endAt);
      if (myTurn !== asked) return;
      show(quoteArea, message("success",
        el("strong", {}, `${fmtTime(quote.start_at)} to ${fmtTime(quote.end_at)}: ${fmtChf(quote.total_chf)}`),
        el("div", { class: "small" },
          `${quote.hours} started hours = ${quote.full_days} full days at ${fmtChf(quote.daily_chf)} + `
          + `${quote.rest_hours} hours at ${fmtChf(quote.hourly_chf)} (capped at the daily rate). `
          + `Deposit ${fmtChf(quote.deposit_chf)}, paid back on return.`)));
      bookButton.disabled = bike.status !== "available";
    } catch (error) {
      if (myTurn === asked) show(quoteArea, errorBox(error));
    }
  }

  bookButton.addEventListener("click", async () => {
    const rental = await run(bookButton, bookErrors, () => api.bookRental(bike.id, period.startAt, period.endAt));
    if (rental) {
      setFlash("success", `Booked ${rental.bike_name} from ${fmtTime(rental.start_at)} to `
        + `${fmtTime(rental.end_at)} for ${fmtChf(rental.quoted_price_chf)}.`);
      location.hash = "#/my";
    }
  });

  const start = query.get("start");
  const end = query.get("end");
  const picker = periodPicker(hours, start && end ? { startAt: start, endAt: end } : null, periodChanged);
  show(area.querySelector("#picker"), picker.element);
}
