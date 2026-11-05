/*
  Staff: the Workshop (#/staff/workshop), SPEC §14.

  The list shows bikes waiting for the diagnostic machine and the open cases.
  One case (#/staff/workshop?case=12) follows a bike from the scan to rentable,
  sold or scrapped:

    scan -> the agent analyses -> staff choose -> they discuss -> the agent
    plans -> they discuss -> staff approve -> repair -> rescan -> done

  The agent works in the background, so this page asks GET /staff/workshop/cases/{id}
  every 2 seconds while it does (/staff calls are free).

  The decision screen is drawn from data, not from the model's text: a bike whose
  parts are coloured by the worst reading, a booking timeline, and option cards
  with bars. Every text from the API goes in as text (el()), the shield of SPEC §7.
  "How the agent worked" at the bottom is for students: each step, in order.
*/

import * as api from "../api.js";
import { el, show, loading, errorBox, message, run, select, setFlash, fmtChf, fmtDay, fmtTime } from "../ui.js";

const POLL_MS = 2_000;
const SCAN_MS = 6_000;      // how long the machine "runs" on screen (SPEC §14.2)
const GROUPS_ON_SCREEN = ["Frame", "Fork and headset", "Wheels", "Tyres", "Hub bearings", "Bottom bracket and cranks",
  "Chain and gears", "Brakes", "Cables and controls", "Saddle, bars and lights", "Battery", "Motor and electronics"];

const STAGES = [["open", "Scan"], ["analysing", "Analysis"], ["choosing", "Your choice"], ["discussing", "Discussion"],
  ["planning", "Planning"], ["plan_review", "Plan review"], ["approved", "Approved"], ["in_repair", "Repair"],
  ["rescan", "Rescan"], ["closed", "Done"]];
const VERDICTS = { fit: ["Fit to rent", "ok"], watch: ["Watch: rentable, check again", "watch"], unfit: ["Not safe to rent", "unfit"] };
const KINDS = { repair: "Repair", repair_and_sell: "Repair and sell", sell_as_is: "Sell as it is", keep_watch: "Keep and watch",
  scrap: "Scrap" };

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- drawing ------------------------------------------------------------------------

/** An SVG element. el() makes HTML elements, and SVG needs its own namespace. */
function svg(tag, attrs = {}, ...children) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attrs)) element.setAttribute(name, value);
  element.append(...children);
  return element;
}

const title = (text) => { const t = svg("title"); t.textContent = text; return t; };

/** A bike side-on. Each group of parts takes its colour from its worst reading. */
function bikeDrawing(groups) {
  const of = Object.fromEntries(groups.map((g) => [g.group, g]));
  const part = (group, ...shapes) => {
    const info = of[group];
    return info ? svg("g", { class: `part ${info.status}` }, title(`${info.label}: ${info.status}`), ...shapes) : svg("g");
  };
  const line = (x1, y1, x2, y2) => svg("line", { x1, y1, x2, y2 });
  const circle = (cx, cy, r) => svg("circle", { cx, cy, r });
  const wheels = (r) => [circle(95, 150, r), circle(305, 150, r)];
  return svg("svg", { viewBox: "0 0 400 215", class: "bike-drawing", role: "img", "aria-label": "Bike, with parts coloured by their condition" },
    part("tyres", ...wheels(62)),
    part("wheels", ...wheels(52)),
    part("hubs", ...wheels(8)),
    part("frame", line(95, 150, 195, 150), line(195, 150, 160, 75), line(160, 75, 270, 75), line(195, 150, 275, 95), line(160, 75, 95, 150)),
    part("fork", line(275, 70, 305, 150)),
    part("controls", line(275, 70, 268, 48), line(268, 48, 298, 42)),
    part("contact", line(160, 75, 152, 48), line(130, 46, 174, 46)),
    part("bottom_bracket", circle(195, 150, 12)),
    part("drivetrain", line(195, 138, 95, 142), line(195, 162, 95, 158)),
    part("brakes", circle(95, 150, 24), circle(305, 150, 24)),
    part("battery", svg("rect", { x: 188, y: 92, width: 56, height: 16, rx: 4, transform: "rotate(-34 216 100)" })),
    part("motor", circle(195, 150, 20)));
}

/** A row of coloured chips naming each group, so colour isn't the only signal. */
function groupChips(groups) {
  const order = { unfit: 0, watch: 1, trend: 2, ok: 3 };
  const words = { unfit: "not safe", watch: "watch", trend: "changing fast", ok: "fine" };
  return el("ul", { class: "chips" }, [...groups].sort((a, b) => order[a.status] - order[b.status]).map((g) =>
    el("li", { class: `chip ${g.status}` }, `${g.label}: ${words[g.status]}`)));
}

const dayNumber = (iso) => new Date(`${iso.slice(0, 10)}T12:00:00Z`).getTime() / 86_400_000;

/** Today, the bookings, and when each option has the bike ready. Bookings an option misses are red. */
function timeline(brief) {
  const start = dayNumber(brief.today);
  const span = dayNumber(brief.timeline_end) - start;
  const left = (iso) => Math.min(Math.max((dayNumber(iso) - start) / span, 0), 1) * 100;
  const place = (node, from, to) => {
    node.style.left = `${left(from)}%`;      // numbers we computed, not API text
    node.style.width = `${Math.max(left(to) - left(from), 1.5)}%`;
    return node;
  };
  const row = (label, ...bars) => el("div", { class: "line-row" }, el("div", { class: "line-label" }, label), el("div", { class: "line-track" }, ...bars));
  const lastDay = (card) => card.work_done || brief.today;
  return el("div", { class: "timeline", role: "img", "aria-label": "Booking timeline" },
    row("Bookings", brief.bookings.map((b) => {
      const risky = brief.options.every((o) => o.bookings_affected.includes(b.rental_id));
      const bar = el("div", { class: `bar-booked ${risky ? "risk" : ""}`, title: `${fmtTime(b.start_at)} to ${fmtTime(b.end_at)}` });
      return place(bar, b.start_at, b.end_at);
    })),
    brief.options.map((o) => row(`Option ${o.key}`, place(el("div", { class: "bar-work" }), brief.today, lastDay(o)),
      brief.bookings.filter((b) => o.bookings_affected.includes(b.rental_id)).map((b) =>
        place(el("div", { class: "bar-clash" }), b.start_at, b.end_at)))),
    el("div", { class: "line-row" }, el("div", { class: "line-label" }), el("div", { class: "line-ends small muted" },
      el("span", {}, `Today, ${fmtDay(brief.today)}`), el("span", {}, fmtDay(brief.timeline_end)))),
    el("p", { class: "small muted" }, "Green: the bike is in the workshop. Grey: a booking. Red: that booking is in trouble with this option."));
}

function scoreBar(label, score) {
  const fill = el("div", { class: "score-fill" });
  fill.style.width = `${score * 20}%`;     // a number from the API's schema, 1 to 5
  return el("div", { class: "score" }, el("span", { class: "score-label" }, label),
    el("div", { class: "score-track", role: "img", "aria-label": `${label}: ${score} of 5` }, fill));
}

function optionCard(brief, option, chooseButton) {
  const recommended = brief.recommended === option.key;
  const clashes = option.bookings_affected.length;
  return el("div", { class: `option ${recommended ? "recommended" : ""}` },
    recommended ? el("div", { class: "ribbon" }, "The agent recommends") : null,
    el("h3", {}, `${option.key}. ${option.title || KINDS[option.kind]}`),
    el("p", {}, option.what_we_do),
    el("dl", { class: "facts" },
      el("dt", {}, "Costs"), el("dd", {}, fmtChf(option.cost_chf)),
      el("dt", {}, "Rentable"), el("dd", {}, option.ready_date ? fmtDay(option.ready_date)
        : (option.kind === "keep_watch" ? "Stays in service" : "Leaves the fleet")),
      el("dt", {}, "Bookings hit"), el("dd", { class: clashes ? "bad" : "" }, clashes ? String(clashes) : "None")),
    scoreBar("Cheap", option.scores.cost), scoreBar("Fast", option.scores.speed), scoreBar("Safe", option.scores.safety),
    option.parts.length ? el("details", {}, el("summary", {}, "Parts"), option.parts.map((p) =>
      el("p", { class: "small" }, `${p.label}: ${p.supplier} (${p.country}), ${fmtChf(p.total_chf)}, ${p.delivery_days} days, ${p.quality.replaceAll("_", " ")}`))) : null,
    chooseButton);
}

// ---- the list -----------------------------------------------------------------------

export async function render(view, { query, flash }) {
  if (query.get("case")) return renderCase(view, Number(query.get("case")));
  await renderList(view, flash);
}

async function renderList(view, flash) {
  const notice = el("div", {}, flash);
  const content = el("div", {}, loading());
  show(view, el("h1", {}, "Workshop"),
    el("p", { class: "muted" }, "The diagnostic machine checks returned bikes, and an AI agent helps you decide what to do."), notice, content);

  let data;
  try {
    data = await api.workshopOverview();
  } catch (error) {
    show(content, errorBox(error));
    return;
  }
  const verdictBadge = (verdict) => el("span", { class: `verdict ${VERDICTS[verdict][1]}` }, VERDICTS[verdict][0]);
  const week = Object.entries(data.mechanic_hours);
  show(content,
    el("h2", {}, `Waiting for the machine (${data.waiting.length})`),
    data.waiting.length ? data.waiting.map((bike) => waitingCard(bike, notice)) : el("p", { class: "muted" }, "No bike is waiting."),
    el("h2", {}, `Open cases (${data.cases.length})`),
    data.cases.length ? data.cases.map((c) => el("div", { class: "card row" },
      el("div", { class: "grow" },
        el("h3", {}, el("a", { href: `#/staff/workshop?case=${c.id}` }, `${c.name} (${c.code})`)),
        el("div", {}, verdictBadge(c.verdict), " ", el("span", { class: "badge" }, STAGES.find(([s]) => s === c.stage)[1]),
          c.bike_status === "maintenance" ? el("span", { class: "badge warn" }, "in maintenance") : null),
        el("div", { class: "small muted" }, c.next_booking ? `Next pick-up: ${fmtTime(c.next_booking)}` : "No bookings ahead",
          c.ready_estimate ? ` · expected back ${fmtDay(c.ready_estimate)}` : "")),
      el("a", { href: `#/staff/workshop?case=${c.id}`, class: "button" }, "Open"))) : el("p", { class: "muted" }, "No open cases."),
    el("h2", {}, "The mechanic's week"),
    week.length ? el("p", {}, week.map(([day, hours]) => `${fmtDay(day)}: ${hours} h`).join(" · ")) : el("p", { class: "muted" }, "Nothing booked."),
    el("p", { class: "small muted" }, `${data.closed} cases closed. The agent uses ${data.model}.`));
}

function waitingCard(bike, notice) {
  const area = el("div", {});
  const button = el("button", { type: "button", class: "primary" }, "Run scan");
  button.addEventListener("click", async () => {
    button.disabled = true;
    const shown = machineRunning(area);        // the machine "runs" on screen; the sums take no time
    const result = await run(null, notice, () => api.runScan(bike.bike_id));
    await shown;
    if (!result) { button.disabled = false; area.replaceChildren(); return; }
    const words = VERDICTS[result.verdict];
    if (result.verdict === "fit") {
      show(area, message("success", "All clear: fit to rent. No case needed."));
      return;
    }
    setFlash(words[1] === "unfit" ? "error" : "warning", `${bike.code}: ${words[0]}.`);
    location.hash = `#/staff/workshop?case=${result.case_id}`;
  });
  return el("div", { class: "card" }, el("div", { class: "row" },
    el("div", { class: "grow" }, el("h3", {}, `${bike.name} (${bike.code})`),
      el("div", { class: "small muted" }, bike.returned_at ? `Returned ${fmtTime(bike.returned_at)}` : "Returned")),
    button), area);
}

/** The groups light up one after the other, for a few seconds. */
async function machineRunning(area) {
  const list = el("ul", { class: "chips" });
  show(area, el("p", { class: "loading" }, "The machine is scanning…"), list);
  for (const group of GROUPS_ON_SCREEN) {
    list.append(el("li", { class: "chip ok" }, group));
    await pause(SCAN_MS / GROUPS_ON_SCREEN.length);
  }
}

// ---- one case -----------------------------------------------------------------------

function renderCase(view, caseId) {
  const top = el("div", {});
  const notice = el("div", {});
  const body = el("div", {});
  show(view, el("p", {}, el("a", { href: "#/staff/workshop" }, "← Back to the Workshop")), top, notice, body);

  /** Tell the server something, then draw the answer. Errors show as the API's sentence. */
  async function act(button, call) {
    const answer = await run(button, notice, call);
    if (answer) refresh(answer.stage ? answer : undefined);
    return answer;
  }

  // What staff are typing. Redrawing the page must never lose it.
  const drafts = {};

  let polling = false;
  async function poll() {
    if (polling) return;
    polling = true;
    while (view.isConnected) {
      await pause(POLL_MS);
      if (!view.isConnected) break;
      try {
        const data = await api.getCase(caseId);
        if (!["working", "waiting"].includes(data.agent_state)) { polling = false; draw(data); return; }
        drawTop(data);
        drawTrail(data);
        status.replaceChildren(...thinkingWords(data));
      } catch (error) {
        show(notice, errorBox(error));
      }
    }
    polling = false;
  }

  async function refresh(data) {
    try {
      draw(data || await api.getCase(caseId));
    } catch (error) {
      show(notice, errorBox(error));
    }
  }

  const trail = el("details", { class: "trail" });
  const status = el("div", { "aria-live": "polite" });     // what the agent is doing right now

  function drawTop(data) {
    const here = STAGES.findIndex(([s]) => s === data.stage);
    const [text, tone] = VERDICTS[data.verdict];
    show(top,
      el("h1", {}, `${data.name} (${data.code})`),
      el("ol", { class: "stages" }, STAGES.map(([stage, label], i) =>
        el("li", { class: i < here ? "done" : i === here ? "now" : "" }, label))),
      el("div", { class: `banner ${tone}` }, el("strong", {}, data.brief ? data.brief.verdict_sentence : text)),
      data.ready_estimate ? el("p", {}, el("strong", {}, `Expected back: ${fmtDay(data.ready_estimate)}`), " (customers see this estimate)") : null);
  }

  function drawTrail(data) {
    const steps = data.events.filter((e) => ["round", "tool", "position", "plan", "decision", "choice", "reminder"].includes(e.kind));
    show(trail, el("summary", {}, `How the agent worked (${data.events.filter((e) => e.kind === "round").length} rounds, ${data.tokens_used} tokens)`),
      el("ol", { class: "steps" }, steps.map((e) => el("li", {},
        el("strong", {}, e.kind === "tool" ? `Tool: ${e.content}` : `${e.author}: ${e.kind}`),
        e.reasoning ? el("p", { class: "small reasoning" }, e.reasoning) : null,
        e.kind === "round" && (e.data?.tool_calls || []).length
          ? el("p", { class: "small muted" }, `Asked for ${e.data.tool_calls.map((c) => c.name).join(", ")}`) : null,
        e.kind !== "tool" && e.content ? el("p", { class: "small" }, e.content) : null))));
  }

  function draw(data) {
    const typing = document.activeElement && document.activeElement.name === "agent-message";
    drawTop(data);
    drawTrail(data);
    show(notice);
    status.replaceChildren(...thinkingWords(data));
    show(body,
      safetyBar(data),
      data.agent_state === "failed" ? stuck(data) : null,
      ["discussing", "plan_review"].includes(data.stage) ? null : status,
      data.stage === "open" ? beforeAnalysis(data) : null,
      data.brief ? briefScreen(data) : null,
      ["discussing", "plan_review"].includes(data.stage) ? conversation(data) : null,
      data.plan ? planScreen(data) : null,
      ["approved", "in_repair", "rescan", "closed"].includes(data.stage) ? afterApproval(data) : null,
      trail);
    if (typing) {           // keep the cursor where it was
      const box = body.querySelector('[name="agent-message"]');
      if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
    }
    if (["working", "waiting"].includes(data.agent_state)) poll();
  }

  function safetyBar(data) {
    if (data.stage === "closed") return null;
    const parts = [];
    if (data.verdict === "unfit" && data.bike_status !== "maintenance") {
      const button = el("button", { type: "button", class: "danger" }, "Put in maintenance");
      button.addEventListener("click", () => act(button, () => api.caseStep(caseId, "maintenance")));
      parts.push(message("error", "This bike isn't safe, and it can still be booked. ", button));
    }
    return parts;
  }

  function stuck(data) {
    const button = el("button", { type: "button", class: "primary" }, "Retry");
    button.addEventListener("click", () => act(button, () => api.caseStep(caseId, "retry")));
    return message("warning", data.agent_note || "The agent stopped.", " ", button);
  }

  function thinkingWords(data) {
    if (data.agent_state === "waiting") return [el("p", { class: "loading" }, `${data.agent_note}…`)];
    if (data.agent_state !== "working") return [];
    const rounds = data.events.filter((e) => e.kind === "round" && e.stage === data.stage).length;
    const talking = ["discussing", "plan_review"].includes(data.stage);
    return [el("p", { class: "loading" }, talking
      ? "The agent is thinking about this. You can keep writing: a new message replaces what it was doing."
      : `The agent is working${rounds ? `, step ${rounds + 1}` : ""}. This can take a few minutes.`)];
  }

  function beforeAnalysis(data) {
    const button = el("button", { type: "button", class: "primary" }, "Analyse with the agent");
    button.addEventListener("click", () => act(button, () => api.caseStep(caseId, "analyse")));
    return [el("div", { class: "brief-top" }, bikeDrawing(data.groups), groupChips(data.groups)),
      el("div", { class: "buttons" }, button)];
  }

  function briefScreen(data) {
    const brief = data.brief;
    const canChoose = ["choosing", "discussing"].includes(data.stage);
    const choice = (option) => {
      if (!canChoose) return data.chosen_option === option.key ? el("p", { class: "chosen" }, "Your choice") : null;
      if (data.chosen_option === option.key) return el("p", { class: "chosen" }, "Your choice");
      const button = el("button", { type: "button", class: "primary" }, data.chosen_option ? `Change to ${option.key}` : `Choose ${option.key}`);
      button.addEventListener("click", () => act(button, () => api.chooseOption(caseId, option.key)));
      return button;
    };
    const part = el("div", { class: "brief" },
      el("div", { class: "brief-top" }, bikeDrawing(brief.groups), el("div", {},
        el("h2", {}, "What's wrong"), el("p", {}, brief.what_is_wrong), groupChips(brief.groups))),
      el("h2", {}, "Bookings"), timeline(brief),
      el("h2", {}, "Your options"),
      el("div", { class: "options" }, brief.options.map((o) => optionCard(brief, o, choice(o)))),
      el("p", { class: "legend" }, el("strong", {}, `Why ${brief.recommended}: `), brief.recommended_why));
    if (["choosing", "discussing"].includes(data.stage)) return part;
    return el("details", {}, el("summary", {}, "The brief"), part);
  }

  function conversation(data) {
    const talk = data.events.filter((e) => e.stage === data.stage && ["message", "position", "choice"].includes(e.kind));
    const input = el("textarea", { name: "agent-message", rows: 3, maxlength: 2000, value: drafts[data.stage] || "",
      placeholder: "Ask the agent, or tell it what you think. Enter sends, Shift+Enter starts a new line.", "aria-label": "Your message" });
    input.addEventListener("input", () => { drafts[data.stage] = input.value; });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
    });
    const send = el("button", { type: "submit", class: "primary" }, "Send");
    const form = el("form", { class: "chat-form" }, input, el("div", { class: "actions" }, send));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      drafts[data.stage] = "";                   // cleared first, so the redraw shows an empty box
      const answer = await act(send, () => api.sendCaseMessage(caseId, text));
      if (!answer) { drafts[data.stage] = text; input.value = text; }    // it failed: keep what they wrote
    });
    const busy = ["working", "waiting"].includes(data.agent_state);

    const position = [...talk].reverse().find((e) => e.kind === "position");
    const disagree = position && position.data && position.data.agrees === false;
    const decide = el("div", { class: "buttons" });
    if (data.stage === "discussing") {
      if (data.staff_can_agree) {
        const failed = data.agent_state === "failed";
        const agreed = el("button", { type: "button", class: disagree ? "danger" : "primary" },
          failed ? `Decide without the agent: write the plan for option ${data.chosen_option}`
            : disagree ? `Keep option ${data.chosen_option} anyway, and write the plan` : "Agreed, write the plan");
        agreed.addEventListener("click", () => act(agreed, () => api.caseStep(caseId, "agree")));
        decide.append(agreed);
      } else {
        decide.append(el("p", { class: "small muted" }, "The agent answers first. Then you decide."));
      }
    } else if (busy) {
      decide.append(el("p", { class: "small muted" }, "The agent is revising the plan. Then you can approve it."));
    } else {
      const approve = el("button", { type: "button", class: "primary" }, `Approve plan version ${data.plan_version}`);
      approve.addEventListener("click", () => act(approve, () => api.caseStep(caseId, "approve-plan")));
      decide.append(approve);
    }
    return [el("h2", {}, data.stage === "discussing" ? "Discuss it with the agent" : "Discuss the plan"),
      el("div", { class: "chat", "aria-live": "polite" }, talk.map((e) => el("div", { class: `bubble ${e.author === "staff" ? "user" : "assistant"}` },
        el("div", { class: "who" }, e.author === "staff" ? "You" : "Agent"),
        el("div", { class: "text" }, e.content),
        e.kind === "position" && e.data ? el("div", { class: "tools" }, e.data.agrees ? "Agrees with your choice"
          : `Disagrees${e.data.prefers ? `: prefers option ${e.data.prefers}` : ""}`) : null))),
      status, form, decide];
  }

  function planScreen(data) {
    const plan = data.plan;
    return el("div", { class: "plan" },
      el("h2", {}, `The plan, version ${plan.version}`),
      data.agent_agreed === false ? message("warning", "The agent disagreed with this choice. Its reasons are under How the agent worked, below.") : null,
      el("p", {}, plan.summary),
      el("div", { class: "stats" },
        el("div", { class: "stat" }, el("div", { class: "label" }, "Total cost"), el("div", { class: "value" }, fmtChf(plan.cost_chf))),
        el("div", { class: "stat" }, el("div", { class: "label" }, "Mechanic"), el("div", { class: "value" }, `${plan.repair_hours} h`)),
        el("div", { class: "stat" }, el("div", { class: "label" }, "Parts arrive"), el("div", { class: "value" }, fmtDay(plan.parts_arrive))),
        el("div", { class: "stat" }, el("div", { class: "label" }, "Rentable"), el("div", { class: "value" }, plan.ready_date ? fmtDay(plan.ready_date) : "Leaves the fleet"))),
      plan.parts.length ? el("ul", {}, plan.parts.map((p) => el("li", {}, `${p.label}: ${p.supplier} (${p.country}), ${fmtChf(p.total_chf)}, ${p.delivery_days} days`))) : null,
      el("ol", {}, plan.steps.map((s) => el("li", {}, s))),
      plan.fallback ? el("p", { class: "small" }, el("strong", {}, "If a part is late: "), plan.fallback) : null,
      plan.sale ? el("p", {}, el("strong", {}, `List price ${fmtChf(plan.sale.list_price_chf)}`), plan.sale.margin_percent ? `, margin ${plan.sale.margin_percent}%` : "",
        plan.sale.below_target ? " (below the 25% target: the market won't pay more)" : "") : null,
      data.stage === "plan_review" && plan.booking_actions.length ? el("div", {}, el("h3", {}, "For the affected bookings"),
        plan.booking_actions.map((a) => el("p", { class: "small" }, `Booking ${a.rental_id}: ${a.action}. ${a.why}`))) : null);
  }

  function afterApproval(data) {
    if (data.stage === "closed") return message("success", `Case closed: ${data.outcome}.`);
    const parts = [];
    if (data.actions.length) parts.push(el("h2", {}, "Customers"), data.actions.map((a) => actionCard(a, data)));
    parts.push(el("h2", {}, "Progress"));
    const buttons = el("div", { class: "buttons" });
    const add = (label, call, kind = "") => {
      const button = el("button", { type: "button", class: kind }, label);
      button.addEventListener("click", () => act(button, call));
      buttons.append(button);
    };
    const kind = data.plan?.kind;
    if (kind === "keep_watch" && data.stage === "approved") {
      add("Keep it in service", () => api.caseStep(caseId, "back-in-service"), "primary");
    }
    if (["repair", "repair_and_sell"].includes(kind) && ["approved", "in_repair"].includes(data.stage)) {
      add("Parts ordered", () => api.recordProgress(caseId, "ordered"));
      add("Parts arrived", () => api.recordProgress(caseId, "arrived"));
      add("Repair done", () => api.recordProgress(caseId, "repaired"), "primary");
    }
    if (data.stage === "rescan") {
      add("Run the rescan", () => api.runScan(data.bike_id), "primary");
      add("Back in service", () => api.caseStep(caseId, "back-in-service"));
    }
    if (kind === "scrap") add("Scrap the bike", () => api.caseStep(caseId, "scrap"), "danger");
    parts.push(buttons);
    const saleReady = kind === "sell_as_is" || (kind === "repair_and_sell" && data.stage === "rescan");
    if (saleReady) {
      const price = el("input", { type: "number", min: 1, step: 10, value: data.plan.sale?.list_price_chf || "", "aria-label": "List price in CHF" });
      const sell = el("button", { type: "button", class: "primary" }, "List for sale at this price");
      sell.addEventListener("click", async () => {
        const answer = await run(sell, notice, () => api.listForSale(caseId, price.value));
        if (answer) refresh();
      });
      parts.push(el("div", { class: "buttons" }, price, sell));
    }
    const date = el("input", { type: "date", value: data.ready_estimate || "", "aria-label": "Expected back" });
    const save = el("button", { type: "button" }, "Save the expected date");
    save.addEventListener("click", () => act(save, () => api.setReadyEstimate(caseId, date.value)));
    parts.push(el("div", { class: "buttons" }, date, save));
    return parts;
  }

  function actionCard(action, data) {
    if (action.status === "done") {
      return el("div", { class: "card" }, `Booking ${action.rental_id}, ${action.customer}: ${action.outcome}`);
    }
    const box = el("div", { class: "card" },
      el("h3", {}, `Booking ${action.rental_id}: ${fmtTime(action.start_at)}, ${action.customer}`),
      el("p", { class: "small muted" }, `Suggested: ${action.kind}. ${action.why}`));
    const text = el("textarea", { rows: 5, value: action.draft, "aria-label": "Email to the customer" });
    const send = el("button", { type: "button", class: "primary" }, "Send email");
    send.addEventListener("click", () => act(send, () => api.sendCustomerEmail(action.id, text.value)));
    const note = el("input", { placeholder: "What came of it?", "aria-label": "Outcome" });
    const done = el("button", { type: "button" }, "Called: tick off");
    done.addEventListener("click", () => {
      if (note.value.trim()) act(done, () => api.finishAction(action.id, note.value.trim()));
    });
    const cancel = el("button", { type: "button", class: "danger" }, "Cancel the booking");
    cancel.addEventListener("click", () => {
      if (confirm(`Cancel booking ${action.rental_id}?`)) act(cancel, () => api.cancelBooking(action.id));
    });
    const others = el("div", {});
    const look = el("button", { type: "button" }, "Show other bikes");
    look.addEventListener("click", async () => {
      const found = await run(look, others, () => api.bookingAlternatives(action.id));
      if (!found) return;
      const bikes = found.other_bikes_same_dates;
      const choice = select(bikes.map((b) => [b.bike_id,
        `${b.code} ${b.name}, ${fmtChf(b.price_chf)} (change: ${fmtChf(b.price_change_chf)})`]), "");
      const move = el("button", { type: "button", class: "primary" }, "Move the booking");
      move.addEventListener("click", () => act(move, () => api.moveBooking(action.id, Number(choice.value))));
      show(others, bikes.length ? el("div", { class: "buttons" }, choice, move) : el("p", { class: "muted" }, "No other bike is free then."),
        found.same_bike_other_dates.length ? el("p", { class: "small" }, "This bike is free on: ",
          found.same_bike_other_dates.map((d) => fmtTime(d.start_at)).join(", ")) : null);
    });
    box.append(text, el("div", { class: "buttons" }, send, look, cancel), el("div", { class: "buttons" }, note, done), others);
    return box;
  }

  return refresh().then(() => {});
}
