/*
  api.js: the only module that talks to the BikeShop API (the only `fetch`).

  Every page calls the functions at the bottom of this file instead of using
  fetch itself. That keeps the HTTP details in one place:

  - URLs are relative ("/api/bikes"): the page and the API share one server.
  - Signed-in calls send the API key as "Authorization: Bearer <key>".
  - The signed-in user (key, username, role, key name) lives in
    sessionStorage, so it is gone when the browser tab closes.
  - A request that takes longer than 2 seconds shows the "Waking up the shop"
    banner; after 60 seconds it gives up.
  - If the server can't be reached at all (it is restarting, or still
    starting), read requests try again every 2 seconds until the 60 seconds
    are up. Requests that change something (POST, PATCH) are never repeated,
    so a booking can't happen twice.
  - An error answer raises ApiError with the API's own sentence ("detail").
    A 401 (key expired or revoked) also signs the user out.
*/

const TIMEOUT_MS = 60_000;      // give up after 60 s
const SLOW_MS = 2_000;          // show the "waking up" banner after 2 s
const RETRY_PAUSE_MS = 2_000;   // wait between tries while the server is unreachable
const CACHE_MS = 60_000;        // keep the catalogue and price list for 1 minute

/** An error to show to the user. `status` is the HTTP status (0 = no answer). */
export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// ---- the signed-in user (sessionStorage) -------------------------------------

const SESSION_KEY = "bikeshop.session";

/** The signed-in user {apiKey, keyName, username, role}, or null. */
export function getSession() {
  const text = sessionStorage.getItem(SESSION_KEY);
  return text ? JSON.parse(text) : null;
}

function saveSession(session) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

// What to do when the API says the key is no longer valid (app.js sets this:
// it goes back to the sign-in page).
let unauthorizedHandler = () => {};
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

// ---- the "waking up" banner --------------------------------------------------

let slowRequests = 0;   // how many requests are taking longer than 2 s right now

function setSlow(change) {
  slowRequests += change;
  const banner = document.getElementById("waking");
  if (banner) banner.hidden = slowRequests === 0;
}

// ---- turning error answers into one readable sentence ------------------------

async function errorMessage(response) {
  let detail = null;
  try {
    detail = (await response.json()).detail;
  } catch {
    // not JSON (e.g. a proxy's HTML error page)
  }
  // FastAPI's own validation errors (422) are a list of problems: join them.
  if (Array.isArray(detail)) {
    return detail.map((problem) => {
      const field = (problem.loc || []).filter((part) => part !== "body" && part !== "query").join(" ");
      return field ? `${field}: ${problem.msg}` : problem.msg;
    }).join("; ") + ".";
  }
  if (detail) return String(detail);
  if (response.status >= 500) return "The shop's server has a problem. Please try again in a minute.";
  return `The shop answered with an error (status ${response.status}).`;
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- the one function that calls fetch ----------------------------------------

/**
 * Send one request and return the parsed JSON answer, or throw ApiError.
 * options: { body: object sent as JSON, params: query parameters, auth: false for sign-in }
 */
async function request(method, path, { body, params, auth = true } = {}) {
  // Leave out filters the user didn't set.
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") query.set(name, value);
  }
  const url = query.toString() ? `${path}?${query}` : path;

  const headers = {};
  const session = getSession();
  if (auth && session) headers.Authorization = `Bearer ${session.apiKey}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const canRetry = method === "GET" || method === "PUT" || method === "DELETE";
  const deadline = Date.now() + TIMEOUT_MS;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let slow = false;
  const slowTimer = setTimeout(() => { slow = true; setSlow(+1); }, SLOW_MS);

  try {
    let response;
    while (true) {
      try {
        response = await fetch(url, {
          method, headers, signal: controller.signal,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (error) {
        if (error.name === "AbortError") {
          throw new ApiError(0, "The shop did not answer within 60 seconds. Please try again.");
        }
        // No answer at all: the server is down, restarting or still starting.
        if (canRetry && Date.now() + RETRY_PAUSE_MS < deadline) {
          await pause(RETRY_PAUSE_MS);
          continue;
        }
        throw new ApiError(0, "Cannot reach the shop right now. Check your internet connection and try again.");
      }
      // 502/503/504 come from a proxy in front of a server that is (re)starting.
      if ([502, 503, 504].includes(response.status) && canRetry && Date.now() + RETRY_PAUSE_MS < deadline) {
        await pause(RETRY_PAUSE_MS);
        continue;
      }
      break;
    }

    if (!response.ok) {
      const message = await errorMessage(response);
      if (response.status === 401 && auth && session) {
        // The key has expired or was revoked: sign out and go to the sign-in page.
        clearSession();
        cache.clear();
        unauthorizedHandler(message);
      }
      throw new ApiError(response.status, message);
    }
    // A change may make cached lists stale (a reserved bike, a new price).
    if (method !== "GET") cache.clear();
    return await response.json();
  } finally {
    clearTimeout(timeout);
    clearTimeout(slowTimer);
    if (slow) setSlow(-1);
  }
}

// ---- a short cache for lists that rarely change ----------------------------------
// Every /api call costs an API token and counts against 60 calls a minute.

const cache = new Map();   // url -> { time, promise }

function cachedGet(path, params) {
  const id = path + JSON.stringify(params || {});
  const hit = cache.get(id);
  if (hit && Date.now() - hit.time < CACHE_MS) return hit.promise;
  const promise = request("GET", path, { params });
  cache.set(id, { time: Date.now(), promise });
  promise.catch(() => cache.delete(id));   // never cache an error
  return promise;
}

// ---- /auth: accounts and API keys (free) ------------------------------------------

/** Random letters and digits, for the key name "web-xxxxxxxx". */
function randomName(length) {
  const letters = "abcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (byte) => letters[byte % letters.length]).join("");
}

/** Sign in: trade username and password for a new API key for this tab. */
export async function signIn(username, password) {
  const answer = await request("POST", "/auth/generate-key", {
    auth: false,
    body: { username, password, name: `web-${randomName(8)}`, expires_in_days: 1 },
  });
  saveSession({ apiKey: answer.api_key, keyName: answer.name, username, role: answer.role });
  return answer;
}

/** Log out: revoke this tab's key, then forget it (even if revoking fails). */
export async function signOut() {
  const session = getSession();
  try {
    if (session) await request("DELETE", `/auth/revoke-key/${encodeURIComponent(session.keyName)}`);
  } finally {
    clearSession();
    cache.clear();
  }
}

export const register = (username, email, password) =>
  request("POST", "/auth/register", { auth: false, body: { username, email, password } });
export const myKeys = () => request("GET", "/auth/my-keys").then((answer) => answer.keys);
export const revokeKey = (name) => request("DELETE", `/auth/revoke-key/${encodeURIComponent(name)}`);

// ---- /billing: API tokens (free) --------------------------------------------------

export const balance = () => request("GET", "/billing/balance");
export const purchaseTokens = (amount) => request("POST", "/billing/purchase-tokens", { body: { amount } });
export const usageStats = (days) => request("GET", "/billing/usage-stats", { params: { days } });
export const rateLimitStatus = () => request("GET", "/billing/rate-limit-status");

// ---- /api: the shop (each call costs API tokens) -------------------------------------

/** filters: purpose, category, frame_size, max_price_chf, condition, q */
export const searchBikes = (filters) => cachedGet("/api/bikes", filters);
export const getBike = (bikeId) => request("GET", `/api/bikes/${bikeId}`);
export const rentalRates = () => cachedGet("/api/rental-rates");
export const openingHours = () => cachedGet("/api/opening-hours");
export const availability = (params) => request("GET", "/api/availability", { params });
export const quoteRental = (bikeId, startAt, endAt) =>
  request("POST", "/api/rentals/quote", { body: { bike_id: bikeId, start_at: startAt, end_at: endAt } });
export const bookRental = (bikeId, startAt, endAt) =>
  request("POST", "/api/rentals", { body: { bike_id: bikeId, start_at: startAt, end_at: endAt } });
export const myRentals = () => request("GET", "/api/rentals");
export const cancelMyRental = (rentalId) => request("POST", `/api/rentals/${rentalId}/cancel`);
export const reserveBike = (bikeId) => request("POST", "/api/orders", { body: { bike_id: bikeId } });
export const myOrders = () => request("GET", "/api/orders");
export const cancelMyOrder = (orderId) => request("POST", `/api/orders/${orderId}/cancel`);
/** The AI assistant (SPEC §13.8): send the conversation, get { job_id } (or { reply, flagged }). 5 tokens. */
export const askAssistant = (messages) => request("POST", "/api/assistant/messages", { body: { messages } });
/** One of your background jobs, e.g. the assistant's answer. Free. */
export const getJob = (jobId) => request("GET", `/api/jobs/${jobId}`);

// ---- /staff: shop staff only (free) ----------------------------------------------------

export const staffBikes = () => request("GET", "/staff/bikes");
export const createBike = (bike) => request("POST", "/staff/bikes", { body: bike });
export const updateBike = (bikeId, changes) => request("PATCH", `/staff/bikes/${bikeId}`, { body: changes });
export const retireBike = (bikeId) => request("POST", `/staff/bikes/${bikeId}/retire`);
export const inventorySummary = () => request("GET", "/staff/inventory");
export const setRentalRate = (category, rate) =>
  request("PUT", `/staff/rental-rates/${encodeURIComponent(category)}`, { body: rate });
/** params: status, date (YYYY-MM-DD), bike_id, user_id, overdue */
export const staffRentals = (params) => request("GET", "/staff/rentals", { params });
export const pickupRental = (rentalId) => request("POST", `/staff/rentals/${rentalId}/pickup`);
export const returnRental = (rentalId) => request("POST", `/staff/rentals/${rentalId}/return`);
export const staffCancelRental = (rentalId) => request("POST", `/staff/rentals/${rentalId}/cancel`);
export const staffOrders = (params) => request("GET", "/staff/orders", { params });
export const completeOrder = (orderId) => request("POST", `/staff/orders/${orderId}/complete`);
export const staffCancelOrder = (orderId) => request("POST", `/staff/orders/${orderId}/cancel`);
/** Anonymous analytics over the last `days` days (1–365), today included. */
export const getAnalytics = (days) => request("GET", "/staff/analytics", { params: { days } });
/** Recent background jobs, newest first. filters: status, kind */
export const listJobs = (filters) => request("GET", "/staff/jobs", { params: filters });

// ---- public ---------------------------------------------------------------------------------

export const health = () => request("GET", "/health", { auth: false });
