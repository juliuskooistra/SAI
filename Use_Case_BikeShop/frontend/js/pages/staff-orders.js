/*
  Staff: orders (#/staff/orders). Complete or cancel reserved sale bikes.

  A reservation holds a sale bike until `expires_at`. When the customer has
  paid and collected the bike, staff press "Complete" (the bike is sold);
  "Cancel" puts the bike back on sale.

  Reservations that run out are released by the scheduler, a separate
  process that runs every 15 minutes. Its last run comes from GET /health.
  Data: GET /staff/orders, POST /staff/orders/{id}/complete and /cancel.
*/

import * as api from "../api.js";
import { el, show, loading, errorBox, message, run, fmtChf, fmtTime } from "../ui.js";

/** "expires in 5 h" / "expires in 2 days" / "expired, waiting for the scheduler" */
function timeLeft(expiresAt) {
  const hours = (new Date(expiresAt) - Date.now()) / 3_600_000;
  if (hours <= 0) return "expired, waiting for the scheduler";
  if (hours < 48) return `expires in ${Math.round(hours)} h`;
  return `expires in ${Math.round(hours / 24)} days`;
}

export async function render(view, { flash }) {
  const schedulerArea = el("div", {});
  const notice = el("div", {}, flash);
  const content = el("div", {}, loading());
  show(view, el("h1", {}, "Orders"), schedulerArea, notice, content);

  // --- the scheduler that releases expired reservations ---
  async function loadScheduler() {
    try {
      const job = (await api.health()).scheduler;
      if (!job.last_run_at) {
        show(schedulerArea, message("warning",
          "The reservation scheduler has not run yet. Expired reservations are not being released."));
      } else {
        show(schedulerArea, message(job.last_ok ? "info" : "warning",
          `Reservation scheduler: last run ${fmtTime(job.last_run_at)} (${job.last_ok ? "OK" : "FAILED"})`
          + (job.last_result ? `: ${job.last_result}` : "")));
      }
    } catch (error) {
      show(schedulerArea, errorBox(error));
    }
  }

  async function act(button, action, order, describe) {
    const result = await run(button, notice, () => action(order.id));
    if (result) {
      show(notice, message("success", describe(result)));
      loadOrders();
    }
  }

  async function loadOrders() {
    let orders;
    try {
      orders = await api.staffOrders();
    } catch (error) {
      show(content, errorBox(error));
      return;
    }
    const reserved = orders.filter((o) => o.status === "reserved");
    const closed = orders.filter((o) => o.status !== "reserved");

    show(content,
      el("h2", {}, `Reserved (${reserved.length})`),
      reserved.length === 0 ? el("p", { class: "muted" }, "No reservations to complete.") : null,
      reserved.map((order) => {
        const complete = el("button", { type: "button", class: "primary", title: "The customer has paid and collected the bike." }, "Complete");
        complete.addEventListener("click", () => act(complete, api.completeOrder, order,
          (o) => `Sold ${o.bike_name} to ${o.username || "the customer"} for ${fmtChf(o.price_chf)}.`));
        const cancel = el("button", { type: "button", class: "danger" }, "Cancel");
        cancel.addEventListener("click", () => act(cancel, api.staffCancelOrder, order,
          (o) => `Reservation of ${o.bike_name} cancelled; the bike is for sale again.`));
        return el("div", { class: "card row" },
          el("div", { class: "grow" },
            el("h3", {}, `${order.bike_name} (${order.bike_code})`),
            el("div", {}, `${fmtChf(order.price_chf)} · ${order.username || order.user_id}`),
            el("div", { class: "small muted" },
              `Reserved ${fmtTime(order.created_at)} · held until ${fmtTime(order.expires_at)} (${timeLeft(order.expires_at)})`)),
          el("div", { class: "buttons" }, complete, cancel));
      }),
      el("details", {},
        el("summary", {}, `Closed orders (${closed.length})`),
        closed.map((o) => el("p", {},
          `${o.bike_name} (${o.bike_code}) · ${fmtChf(o.price_chf)} · ${o.username || o.user_id} · `
          + `${o.status} ${fmtTime(o.closed_at)}`))));
  }

  await Promise.all([loadScheduler(), loadOrders()]);
}
