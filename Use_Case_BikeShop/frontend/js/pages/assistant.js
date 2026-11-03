/*
  The AI assistant (#/assistant), SPEC §13.8.

  - The conversation lives in this browser tab (sessionStorage): gone when
    the tab closes, and "New conversation" clears it. The server keeps none.
  - Sending: POST /api/assistant/messages with the whole conversation (5 API
    tokens). The answer is not in the reply: the server queues it as a
    background job, so this page asks GET /api/jobs/{id} every 2 seconds
    (free) until the job is done, for at most 90 seconds.
  - If the prompt guard refuses a message, the refusal comes back at once.
  - Answers are shown as text (el() / textContent), never as HTML: an answer
    can't run code or add links (the shield, SPEC §7).
*/

import * as api from "../api.js";
import { el, show, message, errorBox } from "../ui.js";

const STORAGE_KEY = "bikeshop.assistant";
const MAX_SENT = 20;              // the API takes at most 20 messages
const MAX_CHARS = 2000;           // ... of at most 2,000 characters
const POLL_MS = 2_000;
const GIVE_UP_MS = 90_000;
const FAILED = "The assistant couldn't answer. Please try again.";

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The conversation of the signed-in user: [{ role, content, tools? }]. */
function load(username) {
  const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
  return saved && saved.username === username ? saved.messages : [];   // another user's: start fresh
}

function save(username, messages) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ username, messages }));
}

/** Ask the server, then wait for the background job's answer. Returns { content, tools }. */
async function getAnswer(messages) {
  const sent = messages.slice(-MAX_SENT).map(({ role, content }) => ({ role, content }));
  const started = await api.askAssistant(sent);
  if (started.flagged) return { content: started.reply, tools: [] };   // refused by the prompt guard

  const deadline = Date.now() + GIVE_UP_MS;
  while (Date.now() < deadline) {
    await pause(POLL_MS);
    const job = await api.getJob(started.job_id);
    if (job.status === "done") return { content: job.result.text, tools: job.result.tools || [] };
    if (job.status === "failed") throw new Error(FAILED);
  }
  throw new Error("The assistant is taking too long. Please try again.");
}

export async function render(view, { session }) {
  let messages = load(session.username);
  const list = el("div", { class: "chat", "aria-live": "polite" });
  const notice = el("div", {});
  const input = el("textarea", {
    rows: 3, maxlength: MAX_CHARS, required: true,
    placeholder: "e.g. Is an e-bike free on Saturday from 10 to 14, and what does it cost?",
    "aria-label": "Your message",
  });
  const sendButton = el("button", { type: "submit", class: "primary" }, "Send");
  const newButton = el("button", { type: "button", onclick: startOver }, "New conversation");
  const form = el("form", { class: "chat-form", onsubmit: send }, input, el("div", { class: "actions" }, sendButton, newButton));

  // Enter sends, Shift+Enter starts a new line.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });

  show(view,
    el("h1", {}, "Assistant"),
    el("p", { class: "legend" },
      "Ask about free bikes, prices, bookings and how busy a day will be. The assistant can book a bike "
      + "for you after you confirm. Answers come from an AI and can be wrong. Your messages go to BFH's "
      + "AI service: don't type personal details. Each message costs 5 API tokens."),
    list, notice, form);
  draw();

  function draw(thinking = false) {
    show(list,
      messages.length === 0 ? el("p", { class: "muted" }, "Ask a question to start.") : null,
      messages.map((m) => el("div", { class: `bubble ${m.role}` },
        el("div", { class: "who" }, m.role === "user" ? "You" : "Assistant"),
        el("div", { class: "text" }, m.content),
        m.tools && m.tools.length ? el("div", { class: "tools" }, `Used: ${m.tools.join(", ")}`) : null)),
      thinking ? el("div", { class: "bubble assistant thinking" }, el("div", { class: "text" }, "Thinking…")) : null);
    list.lastElementChild?.scrollIntoView({ block: "nearest" });
  }

  async function send(event) {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    messages.push({ role: "user", content: text });
    save(session.username, messages);
    input.value = "";
    show(notice);
    sendButton.disabled = true;
    draw(true);
    try {
      const answer = await getAnswer(messages);
      messages.push({ role: "assistant", content: answer.content, tools: answer.tools });
      save(session.username, messages);
    } catch (error) {
      show(notice, error instanceof api.ApiError ? errorBox(error) : message("error", error.message));
    } finally {
      sendButton.disabled = false;
      draw();
      input.focus();
    }
  }

  function startOver() {
    messages = [];
    save(session.username, messages);
    show(notice);
    draw();
    input.focus();
  }
}
