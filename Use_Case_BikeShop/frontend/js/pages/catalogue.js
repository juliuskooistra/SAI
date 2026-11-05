/*
  Catalogue (#/catalogue): bikes for sale ("Buy") and for rent ("Rent").

  Both tabs search GET /api/bikes with the chosen filters. api.js keeps those
  answers for a minute, because each /api call costs an API token.
  The Rent tab can also ask which bikes are free for a period
  (GET /api/availability); each free bike comes with its price.
  The chosen tab and filters are remembered while you look at a bike.
*/

import * as api from "../api.js";
import {
  el, show, select, loading, errorBox, message, run, periodPicker,
  fmtChf, fmtTime, fmtDay, bikeTitle, CATEGORIES, FRAME_SIZES, CONDITIONS,
} from "../ui.js";

// Remembered between visits (as long as the tab is open).
const state = {
  tab: "buy",
  buy: { category: "", frame_size: "", condition: "", max_price_chf: "", q: "" },
  rent: { category: "", frame_size: "", availability: "", q: "" },
  period: null,          // the period last chosen on the Rent tab
  found: null,           // the last availability answer
};

export function render(view) {
  const content = el("div", {});
  const tabButton = (name, label) => el("button", {
    type: "button", role: "tab", "aria-selected": String(state.tab === name),
    onclick: () => { state.tab = name; render(view); },
  }, label);

  show(view,
    el("h1", {}, "Catalogue"),
    el("div", { class: "tabs", role: "tablist" }, tabButton("buy", "Buy"), tabButton("rent", "Rent")),
    content);

  if (state.tab === "buy") drawBuyTab(content);
  else drawRentTab(content);
}

// ---- shared pieces ---------------------------------------------------------------

/** A filter <select> whose first choice, "Any", means no filter. */
function filterSelect(label, options, filters, field, onChange) {
  const box = select([["", "Any"], ...options], filters[field]);
  box.addEventListener("change", () => { filters[field] = box.value; onChange(); });
  return el("label", {}, label, box);
}

/** A text search box that waits until you stop typing. */
function searchBox(filters, onChange) {
  let timer = null;
  const input = el("input", { type: "search", value: filters.q, placeholder: "name, brand, description" });
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { filters.q = input.value.trim(); onChange(); }, 500);
  });
  return el("label", {}, "Search", input);
}

/** One bike in a list: title, details, price, and a link to its page. */
function bikeCard(bike, priceText, link) {
  return el("div", { class: "card row" },
    el("div", { class: "grow" },
      el("h3", {}, el("a", { href: link }, bikeTitle(bike))),
      el("div", { class: "muted small" },
        `${bike.category} · frame ${bike.frame_size} · ${bike.color} · ${bike.year} · ${bike.condition}`),
      bike.status !== "available" ? el("span", { class: "badge warn" }, bike.status) : null,
      bike.ready_estimate ? el("span", { class: "small muted" }, ` Expected back ${fmtDay(bike.ready_estimate)} (an estimate)`) : null),
    el("div", { class: "price" }, priceText),
    el("a", { href: link, class: "button" }, "View"));
}

// ---- Buy -------------------------------------------------------------------------

function drawBuyTab(content) {
  const filters = state.buy;
  const results = el("div", {});

  async function load() {
    show(results, loading());
    try {
      const bikes = await api.searchBikes({ purpose: "sale", ...filters });
      show(results,
        el("p", { class: "muted small" }, `${bikes.length} bikes for sale`),
        bikes.map((bike) => bikeCard(bike, fmtChf(bike.sale_price_chf), `#/bike/${bike.id}`)));
    } catch (error) {
      show(results, errorBox(error));
    }
  }

  const maxPrice = el("input", { type: "number", min: 0, step: 100, value: filters.max_price_chf, placeholder: "no limit" });
  maxPrice.addEventListener("change", () => { filters.max_price_chf = maxPrice.value; load(); });

  show(content,
    el("div", { class: "form-grid" },
      filterSelect("Category", CATEGORIES, filters, "category", load),
      filterSelect("Frame size", FRAME_SIZES, filters, "frame_size", load),
      filterSelect("Condition", CONDITIONS, filters, "condition", load),
      el("label", {}, "Max price (CHF)", maxPrice),
      searchBox(filters, load)),
    results);
  load();
}

// ---- Rent ------------------------------------------------------------------------

async function drawRentTab(content) {
  const filters = state.rent;
  const freeArea = el("div", {});
  const listArea = el("div", {});

  async function loadList() {
    show(listArea, loading());
    try {
      const [bikes, rates] = await Promise.all([api.searchBikes({ purpose: "rental", ...filters }), api.rentalRates()]);
      const rateOf = Object.fromEntries(rates.map((rate) => [rate.category, rate]));
      show(listArea,
        el("p", { class: "muted small" }, `${bikes.length} rental bikes`),
        bikes.map((bike) => {
          const rate = rateOf[bike.category];
          const price = rate ? `${fmtChf(rate.hourly_chf)}/h, ${fmtChf(rate.daily_chf)}/day` : "–";
          return bikeCard(bike, price, `#/bike/${bike.id}`);
        }));
    } catch (error) {
      show(listArea, errorBox(error));
    }
  }

  function drawFound() {
    const found = state.found;
    if (!found) { freeArea.replaceChildren(); return; }
    const period = `?start=${encodeURIComponent(found.start_at)}&end=${encodeURIComponent(found.end_at)}`;
    show(freeArea,
      el("p", {}, `Free from ${fmtTime(found.start_at)} to ${fmtTime(found.end_at)}: ${found.bikes.length} bikes`),
      found.bikes.length === 0
        ? message("info", "No bike is free for that period. Try other times or another category.") : null,
      found.bikes.map(({ bike, quote }) => bikeCard(bike, fmtChf(quote.total_chf), `#/bike/${bike.id}${period}`)));
  }

  show(content,
    el("div", { class: "form-grid" },
      filterSelect("Category", CATEGORIES, filters, "category", loadList),
      filterSelect("Frame size", FRAME_SIZES, filters, "frame_size", loadList),
      filterSelect("Availability", [["available", "Can be booked"], ["maintenance", "In maintenance"]], filters, "availability", loadList),
      searchBox(filters, loadList)),
    el("h2", {}, "Which bikes are free when?"),
    el("div", { id: "period-area" }, loading()),
    freeArea,
    el("h2", {}, "All rental bikes"),
    listArea);
  loadList();
  drawFound();

  // The period inputs need the shop's opening hours.
  const periodArea = content.querySelector("#period-area");
  try {
    const hours = await api.openingHours();
    const picker = periodPicker(hours, state.period, (period) => { state.period = period.startAt ? period : null; });
    const checkButton = el("button", { type: "button", class: "primary" }, "Check availability");
    const checkErrors = el("div", {});
    checkButton.addEventListener("click", async () => {
      const { startAt, endAt } = picker.value();
      if (!startAt) { show(checkErrors, message("error", "The shop is closed then. Please pick other times.")); return; }
      state.found = null;
      drawFound();
      state.found = await run(checkButton, checkErrors, () => api.availability({
        start_at: startAt, end_at: endAt, category: filters.category, frame_size: filters.frame_size,
      })) || null;
      drawFound();
    });
    show(periodArea, picker.element, el("div", { class: "buttons" }, checkButton), checkErrors);
  } catch (error) {
    show(periodArea, errorBox(error));
  }
}
