/*
  Staff: background jobs (#/staff/jobs). Work the worker does outside a
  request, such as sending a booking confirmation email (SPEC §5.8).

  Each job is queued by a request, then picked up by the worker. If it
  fails it is tried again later, up to `max_attempts` times; after that it
  stays "failed" with its last error. This page lists the latest 100 jobs,
  newest first, and can filter them by status and kind. It does not refresh
  by itself: press Refresh.

  Data: GET /staff/jobs?status=…&kind=… /staff calls are free.
*/

import * as api from "../api.js";
import { el, show, table, stat, select, loading, errorBox, message, fmtTime } from "../ui.js";

const STATUSES = ["queued", "running", "done", "failed"];

let filters = { status: "", kind: "" };   // remembered while the tab is open

/** A status as a coloured badge; failed jobs stand out. */
const statusBadge = (status) => el("span", { class: status === "failed" ? "badge warn" : "badge" }, status);

/** What the job produced: the error if it failed, else its result as text. */
function outcome(job) {
  if (job.error) return el("span", { class: "wrap error-text" }, job.error);
  if (job.result) return el("span", { class: "wrap small" }, JSON.stringify(job.result));
  return el("span", { class: "muted" }, "–");
}

export async function render(view, { flash }) {
  const statusSelect = select([["", "All"], ...STATUSES], filters.status, { name: "status" });
  const kindInput = el("input", { type: "text", name: "kind", value: filters.kind, placeholder: "e.g. send_email" });
  const refresh = el("button", { type: "submit", class: "primary" }, "Refresh");
  const form = el("form", { class: "form-grid" },
    el("label", {}, "Status", statusSelect),
    el("label", {}, "Kind", kindInput),
    el("div", {}, refresh));
  const content = el("div", {}, loading());

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    load();
  });
  statusSelect.addEventListener("change", load);

  show(view, el("h1", {}, "Background jobs"), flash, form, content);

  async function load() {
    filters = { status: statusSelect.value, kind: kindInput.value.trim() };
    refresh.disabled = true;
    let jobs;
    try {
      jobs = await api.listJobs(filters);
    } catch (error) {
      // 404: this server has no job queue (yet). Not an error for the user.
      show(content, error.status === 404 ? message("info", "No jobs yet.") : errorBox(error));
      return;
    } finally {
      refresh.disabled = false;
    }

    if (jobs.length === 0) {
      show(content, el("p", { class: "muted" },
        filters.status || filters.kind ? "No jobs match these filters." : "No jobs yet."));
      return;
    }
    const count = (status) => jobs.filter((job) => job.status === status).length;
    show(content,
      el("div", { class: "stats" }, STATUSES.map((status) => stat(status, count(status)))),
      el("p", { class: "small muted" }, `The latest ${jobs.length} jobs, newest first.`),
      table([
        { label: "#", num: true, value: (job) => job.id },
        { label: "Kind", value: (job) => job.kind },
        { label: "Status", value: (job) => statusBadge(job.status) },
        { label: "Attempts", num: true, value: (job) => `${job.attempts} / ${job.max_attempts}` },
        // User ids are long; show the start, the whole id on hover.
        { label: "User", value: (job) => (job.user_id
          ? el("span", { title: job.user_id }, `${job.user_id.slice(0, 8)}…`) : "system") },
        { label: "Queued", value: (job) => fmtTime(job.enqueued_at) },
        { label: "Started", value: (job) => fmtTime(job.started_at) },
        { label: "Finished", value: (job) => fmtTime(job.finished_at) },
        { label: "Result or error", value: outcome },
      ], jobs));
  }

  await load();
}
