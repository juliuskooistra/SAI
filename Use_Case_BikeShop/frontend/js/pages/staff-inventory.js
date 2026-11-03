/*
  Staff: inventory (#/staff/inventory). Every bike, a summary, and forms to
  add, edit and retire bikes.

  - Summary: GET /staff/inventory (counts by purpose, category and status;
    bikes out now; overdue; at risk; reservations expiring soon).
  - Table: GET /staff/bikes (all bikes, sold and retired included).
  - Add: POST /staff/bikes. Sale bikes need a price; rental bikes take their
    price from the price list.
  - Edit: PATCH /staff/bikes/{id} with only the fields that changed. Rental
    bikes can be switched between "available" and "maintenance".
  - Retire: POST /staff/bikes/{id}/retire (not while rented out or reserved).
*/

import * as api from "../api.js";
import {
  el, show, select, table, stat, loading, errorBox, message, run,
  fmtChf, shopToday, CATEGORIES, FRAME_SIZES, CONDITIONS,
} from "../ui.js";

const STATUSES = ["available", "maintenance", "reserved", "sold", "retired"];
let selectedBikeId = null;   // the bike chosen under "Edit or retire"

const bikeLabel = (bike) => `${bike.code}: ${bike.brand} ${bike.name} (${bike.status})`;

export async function render(view, { flash }) {
  const notice = el("div", {}, flash);
  const content = el("div", {}, loading());
  show(view, el("h1", {}, "Inventory"), notice, content);

  /** After a change: show what happened and draw the page again with fresh data. */
  const done = (text) => { show(notice, message("success", text)); load(); };

  async function load() {
    let summary, bikes;
    try {
      [summary, bikes] = await Promise.all([api.inventorySummary(), api.staffBikes()]);
    } catch (error) {
      show(content, errorBox(error));
      return;
    }
    show(content,
      drawSummary(summary),
      el("h2", {}, `All bikes (${bikes.length})`),
      table([
        { label: "ID", value: (b) => b.id, num: true },
        { label: "Code", value: (b) => b.code },
        { label: "Name", value: (b) => b.name },
        { label: "Brand", value: (b) => b.brand },
        { label: "Purpose", value: (b) => b.purpose },
        { label: "Category", value: (b) => b.category },
        { label: "Frame", value: (b) => b.frame_size },
        { label: "Colour", value: (b) => b.color },
        { label: "Year", value: (b) => b.year, num: true },
        { label: "Condition", value: (b) => b.condition },
        { label: "Sale price", value: (b) => (b.sale_price_chf ? fmtChf(b.sale_price_chf) : ""), num: true },
        { label: "Status", value: (b) => b.status },
      ], bikes),
      el("h2", {}, "Add a bike"),
      addBikeForm(notice, done),
      el("h2", {}, "Edit or retire a bike"),
      editArea(bikes, notice, done));
  }
  await load();
}

// ---- summary ----------------------------------------------------------------------

function drawSummary(summary) {
  // Counts as a table: one row per purpose + category, one column per status.
  const rows = new Map();
  for (const { purpose, category, status, count } of summary.counts) {
    const id = `${purpose} ${category}`;
    if (!rows.has(id)) rows.set(id, { purpose, category });
    rows.get(id)[status] = (rows.get(id)[status] || 0) + count;
  }
  return [
    el("div", { class: "stats" },
      stat("Rental bikes out now", summary.rental_bikes_out_now),
      stat("Overdue rentals", summary.overdue_rentals.length),
      stat("At-risk bookings", summary.at_risk_bookings.length),
      stat("Reservations expiring within 24 h", summary.orders_expiring_within_24h.length)),
    table([
      { label: "Purpose", value: (r) => r.purpose },
      { label: "Category", value: (r) => r.category },
      ...STATUSES.map((s) => ({ label: s, value: (r) => r[s] || 0, num: true })),
    ], [...rows.values()]),
  ];
}

// ---- add a bike ------------------------------------------------------------------------

function addBikeForm(notice, done) {
  const field = (name, attrs = {}) => el("input", { name, ...attrs });
  const inputs = {
    code: field("code", { placeholder: "R-CITY-09 or S-ROAD-12", required: true }),
    name: field("name", { required: true }),
    brand: field("brand", { required: true }),
    purpose: select(["rental", "sale"], "rental", { name: "purpose" }),
    category: select(CATEGORIES, "city", { name: "category" }),
    frame_size: select(FRAME_SIZES, "M", { name: "frame_size" }),
    color: field("color", { required: true }),
    year: field("year", { type: "number", min: 1990, max: 2100, value: shopToday().slice(0, 4), required: true }),
    condition: select(CONDITIONS, "used", { name: "condition" }),
    sale_price_chf: field("sale_price_chf", { type: "number", min: 0, step: 50 }),
    description: el("textarea", { name: "description" }),
  };
  const addButton = el("button", { type: "submit", class: "primary" }, "Add bike");
  const form = el("form", { class: "form-grid" },
    el("label", {}, "Code", inputs.code), el("label", {}, "Name", inputs.name),
    el("label", {}, "Brand", inputs.brand), el("label", {}, "Purpose", inputs.purpose),
    el("label", {}, "Category", inputs.category), el("label", {}, "Frame size", inputs.frame_size),
    el("label", {}, "Colour", inputs.color), el("label", {}, "Year", inputs.year),
    el("label", {}, "Condition (rental bikes are always used)", inputs.condition),
    el("label", {}, "Sale price (CHF, sale bikes only)", inputs.sale_price_chf),
    el("label", { class: "wide" }, "Description", inputs.description),
    el("div", {}, addButton));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const bike = Object.fromEntries(Object.entries(inputs).map(([name, input]) => [name, input.value.trim()]));
    bike.year = Number(bike.year);
    bike.sale_price_chf = bike.purpose === "sale" && bike.sale_price_chf !== "" ? Number(bike.sale_price_chf) : null;
    const created = await run(addButton, notice, () => api.createBike(bike));
    if (created) done(`Added ${bikeLabel(created)}.`);
  });
  return form;
}

// ---- edit or retire ---------------------------------------------------------------------

function editArea(bikes, notice, done) {
  if (bikes.length === 0) return el("p", { class: "muted" }, "No bikes yet.");
  if (!bikes.some((b) => b.id === selectedBikeId)) selectedBikeId = bikes[0].id;

  const chooser = select(bikes.map((b) => [b.id, bikeLabel(b)]), selectedBikeId);
  const formArea = el("div", {});
  chooser.addEventListener("change", () => { selectedBikeId = Number(chooser.value); drawForm(); });

  function drawForm() {
    const bike = bikes.find((b) => b.id === selectedBikeId);
    if (bike.status === "retired") {
      show(formArea, message("info", "This bike is retired. Retired bikes can no longer be edited."));
      return;
    }
    const inputs = {
      name: el("input", { value: bike.name }),
      brand: el("input", { value: bike.brand }),
      color: el("input", { value: bike.color }),
      category: select(CATEGORIES, bike.category),
      frame_size: select(FRAME_SIZES, bike.frame_size),
      year: el("input", { type: "number", min: 1990, max: 2100, value: bike.year }),
      condition: select(CONDITIONS, bike.condition),
      description: el("textarea", { value: bike.description }),
    };
    if (bike.purpose === "sale") {
      inputs.sale_price_chf = el("input", { type: "number", min: 0, step: 50, value: Number(bike.sale_price_chf || 0) });
    }
    if (bike.purpose === "rental" && ["available", "maintenance"].includes(bike.status)) {
      inputs.status = select(["available", "maintenance"], bike.status);
    }
    const labels = { name: "Name", brand: "Brand", color: "Colour", category: "Category", frame_size: "Frame size",
      year: "Year", condition: "Condition", sale_price_chf: "Sale price (CHF)",
      status: "Status (bookings stay when a bike goes into maintenance; they show as at risk)",
      description: "Description" };

    const saveButton = el("button", { type: "submit", class: "primary" }, "Save changes");
    const form = el("form", { class: "form-grid" },
      Object.entries(inputs).map(([name, input]) =>
        el("label", { class: name === "description" ? "wide" : null }, labels[name], input)),
      el("div", {}, saveButton));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      // Send only what changed; PATCH leaves the other fields alone.
      const changes = {};
      for (const [name, input] of Object.entries(inputs)) {
        const value = input.value.trim();
        const changed = ["year", "sale_price_chf"].includes(name)
          ? Number(value) !== Number(bike[name] || 0) : value !== bike[name];
        if (changed) changes[name] = ["year", "sale_price_chf"].includes(name) ? Number(value) : value;
      }
      if (Object.keys(changes).length === 0) { show(notice, message("info", "Nothing changed.")); return; }
      const updated = await run(saveButton, notice, () => api.updateBike(bike.id, changes));
      if (updated) done(`Saved ${bikeLabel(updated)}.`);
    });

    let retirePart = null;
    if (bike.status !== "sold") {
      const retireButton = el("button", { type: "button", class: "danger" }, `Retire ${bike.code}`);
      retireButton.addEventListener("click", async () => {
        if (!confirm(`Retire ${bike.code} for good?`)) return;
        const retired = await run(retireButton, notice, () => api.retireBike(bike.id));
        if (retired) done(`Retired ${bikeLabel(retired)}.`);
      });
      retirePart = [el("p", { class: "muted small" },
        "Retiring takes the bike out of the shop for good (it stays in this table)."), retireButton];
    }
    show(formArea, form, retirePart);
  }

  drawForm();
  return el("div", {}, el("label", {}, "Bike", chooser), formArea);
}
