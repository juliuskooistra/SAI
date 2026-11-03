/*
  My rentals and orders (#/my), each with a Cancel button.

  - Rentals: GET /api/rentals. A booking can be cancelled for free until its
    pick-up time (POST /api/rentals/{id}/cancel).
  - Orders: GET /api/orders. A reserved bike is held until `expires_at`; after
    that the shop's scheduler releases it (POST /api/orders/{id}/cancel to
    cancel it yourself).
  Loading the page costs 2 API tokens.
*/

import * as api from "../api.js";
import { el, show, loading, errorBox, message, run, fmtChf, fmtTime } from "../ui.js";

export async function render(view, { flash }) {
  const notice = el("div", {}, flash);
  const rentalsArea = el("div", {}, loading());
  const ordersArea = el("div", {}, loading());
  show(view,
    el("h1", {}, "My rentals and orders"),
    notice,
    el("h2", {}, "Rentals"), rentalsArea,
    el("h2", {}, "Orders"), ordersArea);

  // After a cancel: show what happened and load the lists again.
  const reload = (text) => { show(notice, message("success", text)); load(); };

  async function load() {
    const [rentals, orders] = await Promise.allSettled([api.myRentals(), api.myOrders()]);
    if (rentals.status === "rejected") show(rentalsArea, errorBox(rentals.reason));
    else drawRentals(rentalsArea, rentals.value, notice, reload);
    if (orders.status === "rejected") show(ordersArea, errorBox(orders.reason));
    else drawOrders(ordersArea, orders.value, notice, reload);
  }
  await load();
}

function drawRentals(area, rentals, notice, reload) {
  if (rentals.length === 0) {
    show(area, message("info", "You have no rentals yet. Find a bike under ", el("a", { href: "#/catalogue" }, "Catalogue → Rent"), "."));
    return;
  }
  show(area, rentals.map((rental) => {
    const cancelButton = rental.status === "booked"
      ? el("button", { type: "button", class: "danger" }, "Cancel") : null;
    cancelButton?.addEventListener("click", async () => {
      if (await run(cancelButton, notice, () => api.cancelMyRental(rental.id))) {
        reload(`Your booking of ${rental.bike_name} is cancelled.`);
      }
    });
    return el("div", { class: "card row" },
      el("div", { class: "grow" },
        el("h3", {}, `${rental.bike_name} (${rental.bike_code})`),
        el("div", {}, `${fmtTime(rental.start_at)} → ${fmtTime(rental.end_at)}`),
        el("div", { class: "small" },
          el("span", { class: "badge" }, rental.status), " ",
          `Quoted ${fmtChf(rental.quoted_price_chf)}`,
          rental.final_price_chf ? ` · final ${fmtChf(rental.final_price_chf)}` : ""),
        rental.overdue ? el("div", { class: "badge warn" }, "Overdue: please bring the bike back") : null),
      cancelButton);
  }));
}

function drawOrders(area, orders, notice, reload) {
  if (orders.length === 0) {
    show(area, message("info", "You have no orders yet. Find a bike under ", el("a", { href: "#/catalogue" }, "Catalogue → Buy"), "."));
    return;
  }
  show(area, orders.map((order) => {
    const reserved = order.status === "reserved";
    const cancelButton = reserved ? el("button", { type: "button", class: "danger" }, "Cancel") : null;
    cancelButton?.addEventListener("click", async () => {
      if (await run(cancelButton, notice, () => api.cancelMyOrder(order.id))) {
        reload(`Your reservation of ${order.bike_name} is cancelled.`);
      }
    });
    return el("div", { class: "card row" },
      el("div", { class: "grow" },
        el("h3", {}, `${order.bike_name} (${order.bike_code})`),
        el("div", { class: "small" }, el("span", { class: "badge" }, order.status), " ", fmtChf(order.price_chf)),
        reserved
          ? el("div", {}, `Held for you until ${fmtTime(order.expires_at)}. Pay and collect it in the shop.`) : null),
      cancelButton);
  }));
}
