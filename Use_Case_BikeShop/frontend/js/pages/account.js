/*
  Account (#/account): API tokens, usage, rate limits and API keys.

  Every /api call costs tokens (a search 1, a booking 5). When they run out
  the API answers 402 and the other pages link here. Buying tokens is a demo
  without real payment (POST /billing/purchase-tokens).
  This tab signed in with its own key ("web-…"); other keys (other tabs,
  devices, scripts) can be revoked here. /billing and /auth calls are free.
*/

import * as api from "../api.js";
import { el, show, select, table, stat, loading, errorBox, message, run, fmtNumber, fmtTime } from "../ui.js";

export async function render(view, { session, flash }) {
  const notice = el("div", {}, flash);
  const balanceArea = el("div", {}, loading());
  const usageArea = el("div", {}, loading());
  const keysArea = el("div", {}, loading());

  // --- buy tokens ---
  const amount = el("input", { type: "number", min: 1, max: 10000, step: 1, value: 100, required: true });
  const buyButton = el("button", { type: "submit", class: "primary" }, "Buy tokens");
  const buyForm = el("form", { class: "form-grid" },
    el("label", {}, "Tokens to buy (demo, no payment)", amount), el("div", {}, buyButton));
  buyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const result = await run(buyButton, notice, () => api.purchaseTokens(Number(amount.value)));
    if (result) {
      show(notice, message("success",
        `Added ${fmtNumber(result.tokens_added)} tokens. New balance: ${fmtNumber(result.new_balance)}.`));
      loadBalance();
    }
  });

  // --- usage period ---
  const period = select([[1, "last day"], [7, "last 7 days"], [30, "last 30 days"]], 30);
  period.addEventListener("change", () => loadUsage());

  show(view,
    el("h1", {}, "Account"),
    el("p", {}, `Signed in as ${session.username} (role: ${session.role}).`),
    notice,
    el("h2", {}, "API tokens"), balanceArea, buyForm,
    el("h2", {}, "Usage"), el("div", { class: "form-grid" }, el("label", {}, "Period", period)), usageArea,
    el("h2", {}, "My API keys"), keysArea);

  async function loadBalance() {
    try {
      const balance = await api.balance();
      show(balanceArea, el("div", { class: "stats" },
        stat("Balance", fmtNumber(balance.current_balance)),
        stat("Bought in total", fmtNumber(balance.total_purchased)),
        stat("Used in total", fmtNumber(balance.total_used))));
    } catch (error) {
      show(balanceArea, errorBox(error));
    }
  }

  async function loadUsage() {
    show(usageArea, loading());
    try {
      const [usage, limits] = await Promise.all([api.usageStats(Number(period.value)), api.rateLimitStatus()]);
      show(usageArea,
        el("div", { class: "stats" },
          stat("Requests", fmtNumber(usage.total_requests)),
          stat("Tokens used", fmtNumber(usage.total_tokens_consumed))),
        usage.endpoint_breakdown.length ? table([
          { label: "Endpoint", value: (row) => row.endpoint },
          { label: "Requests", value: (row) => fmtNumber(row.requests), num: true },
          { label: "Tokens", value: (row) => fmtNumber(row.tokens), num: true },
        ], usage.endpoint_breakdown) : null,
        el("p", { class: "muted small" }, "Rate limit: " + ["minute", "hour", "day"].map((p) =>
          `${limits.remaining[p]} of ${limits.limits[`requests_per_${p}`]} left this ${p}`).join(", ") + "."));
    } catch (error) {
      show(usageArea, errorBox(error));
    }
  }

  async function loadKeys() {
    try {
      const keys = await api.myKeys();
      show(keysArea,
        keys.map((key) => {
          const thisTab = key.name === session.keyName;
          const revokeButton = key.is_active && !thisTab
            ? el("button", { type: "button", class: "danger" }, "Revoke") : null;
          revokeButton?.addEventListener("click", async () => {
            if (await run(revokeButton, notice, () => api.revokeKey(key.name))) {
              show(notice, message("success", `Key ${key.name} is revoked.`));
              loadKeys();
            }
          });
          return el("div", { class: "card row" },
            el("div", { class: "grow" },
              el("strong", {}, key.name), thisTab ? " (this browser tab)" : "",
              el("div", { class: "small muted" },
                `${key.is_active ? "active" : "revoked"} · created ${fmtTime(key.created_at)} · last used ${fmtTime(key.last_used)}`)),
            revokeButton);
        }),
        el("p", { class: "muted small" }, "To revoke this tab's key, use Log out at the top."));
    } catch (error) {
      show(keysArea, errorBox(error));
    }
  }

  await Promise.all([loadBalance(), loadUsage(), loadKeys()]);
}
