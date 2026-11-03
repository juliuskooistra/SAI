/*
  ui.js: small helpers shared by the pages. Nothing in here calls the API.

  - el(): builds HTML elements safely. Text from the API is always added as
    text (a text node), never as HTML, so a bike named "<script>…" is shown
    as those characters and can't run code. This is "the shield" (SPEC §7).
    No file in this frontend uses innerHTML.
  - Formatting: times in shop time (Europe/Zurich), money in CHF.
  - Messages: errors, success messages, and a "flash" message that survives
    one page change (e.g. "Booked!" shown on My rentals).
  - periodPicker(): the date + time inputs for a rental, on the 15-minute grid.
*/

export const CATEGORIES = ["city", "ebike", "mountain", "road", "gravel", "kids", "cargo"];
export const FRAME_SIZES = ["XS", "S", "M", "L", "XL"];
export const CONDITIONS = ["new", "used"];
const SHOP_TIMEZONE = "Europe/Zurich";

// ---- building elements -------------------------------------------------------

/**
 * el("button", { class: "primary", onclick: save }, "Save")
 * attrs: on… = event handler; value/checked/disabled/hidden = set as property;
 *        anything else = an HTML attribute. null/false/undefined attrs are skipped.
 * children: strings and numbers become text; elements are added as they are.
 */
export function el(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith("on")) element.addEventListener(name.slice(2), value);
    else if (["value", "checked", "disabled", "hidden", "selected"].includes(name)) element[name] = value;
    else element.setAttribute(name, value === true ? "" : String(value));
  }
  append(element, children);
  return element;
}

function append(parent, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(parent, child);
    else if (child instanceof Node) parent.append(child);
    else parent.append(document.createTextNode(String(child)));   // text, never HTML
  }
}

/** Replace everything inside `parent` with `children`. */
export function show(parent, ...children) {
  parent.replaceChildren();
  append(parent, children);
}

/** A <select>. options: list of values or [value, label] pairs. */
export function select(options, selected, attrs = {}) {
  return el("select", attrs, options.map((option) => {
    const [value, label] = Array.isArray(option) ? option : [option, option];
    return el("option", { value, selected: String(value) === String(selected) }, label);
  }));
}

/** A table. columns: [{ label, value: (row) => text or element, num: true for numbers }] */
export function table(columns, rows) {
  return el("div", { class: "table-wrap" },
    el("table", {},
      el("thead", {}, el("tr", {}, columns.map((c) => el("th", { class: c.num ? "num" : null }, c.label)))),
      el("tbody", {}, rows.map((row) =>
        el("tr", {}, columns.map((c) => el("td", { class: c.num ? "num" : null }, c.value(row))))))));
}

/** A big number with a label. */
export function stat(label, value) {
  return el("div", { class: "stat" }, el("div", { class: "label" }, label), el("div", { class: "value" }, value));
}

/** "Loading…" placeholder while a page waits for the API. */
export const loading = () => el("p", { class: "loading" }, "Loading…");

// ---- messages ---------------------------------------------------------------------

/** kind: "error" | "success" | "info" | "warning" */
export function message(kind, ...content) {
  return el("div", { class: `message ${kind}`, role: kind === "error" ? "alert" : "status" }, ...content);
}

/** An error from api.js, shown as the API's sentence. 402 (out of tokens) links to Account. */
export function errorBox(error) {
  const text = error && error.message ? error.message : String(error);
  const link = error && error.status === 402 ? el("a", { href: "#/account" }, "Buy more API tokens on the Account page") : null;
  return message("error", text, link);
}

/**
 * Run an async action from a button: disable the button meanwhile, and show
 * an error in `messageArea` if it fails. Returns the result, or undefined on error.
 */
export async function run(button, messageArea, action) {
  if (button) button.disabled = true;
  if (messageArea) messageArea.replaceChildren();
  try {
    return await action();
  } catch (error) {
    if (messageArea) messageArea.replaceChildren(errorBox(error));
    else console.warn(error);
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

// A message shown once on the next page (set before changing location.hash).
let flashMessage = null;
export function setFlash(kind, text) { flashMessage = { kind, text }; }
export function takeFlash() {
  const flash = flashMessage;
  flashMessage = null;
  return flash ? message(flash.kind, flash.text) : null;
}

// ---- formatting --------------------------------------------------------------------

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: SHOP_TIMEZONE, weekday: "short", day: "numeric", month: "short",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

/** "2026-11-07T10:00:00+01:00" -> "Sat 7 Nov 10:00" (shop time). */
export function fmtTime(isoText) {
  if (!isoText) return "–";
  const parts = Object.fromEntries(timeFormat.formatToParts(new Date(isoText)).map((p) => [p.type, p.value]));
  return `${parts.weekday} ${parts.day} ${parts.month} ${parts.hour}:${parts.minute}`;
}

/** "2026-11-07" -> "Sat 7 Nov". */
export function fmtDay(day) {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB",
    { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" });
}

/** "1250.00" -> "CHF 1'250.00" (the API sends money as text). */
export function fmtChf(amount) {
  if (amount === null || amount === undefined) return "–";
  return "CHF " + Number(amount).toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Whole numbers with a thousands separator: 10000 -> "10'000". */
export const fmtNumber = (n) => Number(n).toLocaleString("de-CH", { maximumFractionDigits: 0 });

/** "Flyer Upstreet 5 (R-EBIKE-01)"; no double brand for names like "Stromer ST3". */
export function bikeTitle(bike) {
  const name = bike.name.startsWith(bike.brand) ? bike.name : `${bike.brand} ${bike.name}`;
  return `${name} (${bike.code})`;
}

// ---- dates in shop time ----------------------------------------------------------------
// Days are handled as "YYYY-MM-DD" text. The API reads a time without an
// offset ("2026-11-07T10:00") as Zurich time, which is what we send.

/** Today's date in Zurich, "YYYY-MM-DD" (the computer may be in another time zone). */
export function shopToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: SHOP_TIMEZONE }).format(new Date());
}

/** "2026-11-07" + 2 -> "2026-11-09". */
export function addDays(day, count) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + count);
  return date.toISOString().slice(0, 10);
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Opening hours of one day from GET /api/opening-hours: {opens, closes}, or null if closed. */
function hoursOn(openingHours, day) {
  if (openingHours.closed_days.some((closed) => closed.date === day)) return null;
  const weekday = WEEKDAYS[new Date(`${day}T12:00:00Z`).getUTCDay()];
  const entry = openingHours.weekly.find((d) => d.weekday === weekday);
  return entry && entry.opens ? entry : null;
}

/** Every quarter hour from "09:00" to "18:30", both included. */
function quarterHours(opens, closes) {
  const toMinutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
  const times = [];
  for (let m = toMinutes(opens); m <= toMinutes(closes); m += 15) {
    times.push(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
  }
  return times;
}

/** The first day from tomorrow on that the shop is open. */
function nextOpenDay(openingHours) {
  let day = addDays(shopToday(), 1);
  while (!hoursOn(openingHours, day)) day = addDays(day, 1);
  return day;
}

/**
 * Inputs for a rental period: pick-up date, pick-up time, return day and
 * return time. Times are quarter hours within that day's opening hours.
 *
 * openingHours: the answer of GET /api/opening-hours
 * initial: { startAt, endAt } as "YYYY-MM-DDTHH:MM…", or null for tomorrow 10:00–15:00
 * onChange({ startAt, endAt }): called on every change; startAt is null if the shop is closed then
 * Returns { element, value() }.
 */
export function periodPicker(openingHours, initial, onChange) {
  const today = shopToday();
  const startDay = initial ? initial.startAt.slice(0, 10) : nextOpenDay(openingHours);
  const extraDays = initial
    ? Math.round((new Date(initial.endAt.slice(0, 10)) - new Date(startDay)) / 86_400_000) : 0;
  let wantedStart = initial ? initial.startAt.slice(11, 16) : "10:00";
  let wantedEnd = initial ? initial.endAt.slice(11, 16) : "15:00";

  const dayInput = el("input", { type: "date", name: "pickup-date", min: today, max: addDays(today, 60), value: startDay, required: true });
  const startSelect = el("select", { name: "pickup-time" });
  const daysSelect = select(
    Array.from({ length: 15 }, (_, n) => [n, n === 0 ? "Same day" : n === 1 ? "Next day" : `After ${n} days`]),
    extraDays, { name: "return-after" });
  const endSelect = el("select", { name: "return-time" });
  const note = el("p", { class: "small muted" });

  // Fill a time <select> for one day; keep the wanted time if the shop is open then.
  function fillTimes(selectBox, day, wanted, pickLast) {
    const hours = hoursOn(openingHours, day);
    const times = hours ? quarterHours(hours.opens, hours.closes) : [];
    const chosen = times.includes(wanted) ? wanted : (pickLast ? times[times.length - 1] : times[0]);
    selectBox.replaceChildren(...times.map((t) => el("option", { value: t, selected: t === chosen }, t)));
    selectBox.disabled = times.length === 0;
    return hours;
  }

  function value() {
    const pickupDay = dayInput.value;
    if (!pickupDay || startSelect.disabled || endSelect.disabled) return { startAt: null, endAt: null };
    const returnDay = addDays(pickupDay, Number(daysSelect.value));
    return { startAt: `${pickupDay}T${startSelect.value}`, endAt: `${returnDay}T${endSelect.value}` };
  }

  function refresh() {
    const pickupDay = dayInput.value;
    if (!pickupDay) { note.textContent = "Choose a pick-up date."; onChange(value()); return; }
    const returnDay = addDays(pickupDay, Number(daysSelect.value));
    const openStart = fillTimes(startSelect, pickupDay, wantedStart, false);
    const openEnd = fillTimes(endSelect, returnDay, wantedEnd, true);
    if (!openStart) note.textContent = `The shop is closed on ${fmtDay(pickupDay)}. Please pick another day.`;
    else if (!openEnd) note.textContent = `The shop is closed on ${fmtDay(returnDay)}, so you can't return the bike then.`;
    else note.textContent = `Pick-up ${fmtDay(pickupDay)} ${openStart.opens}–${openStart.closes}, `
      + `return ${fmtDay(returnDay)} ${openEnd.opens}–${openEnd.closes}.`;
    onChange(value());
  }

  dayInput.addEventListener("change", refresh);
  daysSelect.addEventListener("change", refresh);
  startSelect.addEventListener("change", () => { wantedStart = startSelect.value; onChange(value()); });
  endSelect.addEventListener("change", () => { wantedEnd = endSelect.value; onChange(value()); });

  const element = el("div", {},
    el("div", { class: "form-grid" },
      el("label", {}, "Pick-up date", dayInput),
      el("label", {}, "Pick-up time", startSelect),
      el("label", {}, "Return", daysSelect),
      el("label", {}, "Return time", endSelect)),
    note);
  // Fill the selects now, but tell the page only after it has the element.
  queueMicrotask(refresh);
  return { element, value };
}
