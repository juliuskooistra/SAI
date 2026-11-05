# The Workshop: an AI agent that argues back

A small bike shop has one mechanic and very little time between one rental and
the next. A diagnostic machine scans every returned bike. An AI agent reads the
scan, explains the problem in plain words, **discusses** the options with a staff
member, writes the plan, and says when the bike can be rented again. The contract
is [SPEC §14](SPEC.md).

This is a case study in LLM workflows. Everything the agent does is visible on the
page under *How the agent worked*.

## The one idea to understand

**The agent reasons and argues, our code checks the facts and the safety limits,
and the human decides.**

| Who | Does what | Why it isn't someone else's job |
|---|---|---|
| **Code** | Measures, applies the safety limits, computes every price and date | These must be exactly right, every time |
| **Agent** | Finds the cause, weighs the paths, explains, disagrees | This needs judgement over a lot of data |
| **Human** | Decides, talks to customers, turns the spanner | Responsibility stays with a person |

Compare the customer assistant ([ASSISTANT.md](ASSISTANT.md)). There, one message
leads to one answer. Here, the workflow runs over days, with a person in the middle.

```
 scan ─▶ ANALYSE ─▶ BRIEF ─▶ DISCUSS ─▶ PLAN ─▶ PLAN REVIEW ─▶ APPROVED ─▶ repair ─▶ rescan
 code     agent     human    both       agent    both           human      human     code
```

## Files

| File | What it is |
|---|---|
| [api/tools/workshop_tools.py](api/tools/workshop_tools.py) | **Start here.** The read-only tools, the menu the AI sees, and its rules (`RULES`) |
| [api/services/workshop_agent.py](api/services/workshop_agent.py) | The loop: one model round per job, the budget, rebuilding the conversation |
| [api/services/workshop_service.py](api/services/workshop_service.py) | Everything except the AI: stages, costs, dates, checks, staff actions |
| [api/services/scan_service.py](api/services/scan_service.py) | The simulated machine and the safety gate |
| [frontend/js/pages/staff-workshop.js](frontend/js/pages/staff-workshop.js) | The page: drawing, timeline, option cards, discussion |
| [scripts/seed_workshop.py](scripts/seed_workshop.py) | The data, with the planted cases D1–D10 |
| [scripts/workshop_evaluate.py](scripts/workshop_evaluate.py) | Scores the agent against the answer key |

## Run it

```bash
set -a; . ./.env; set +a          # needs MLMP_API_KEY; the model is WORKSHOP_MODEL
.venv/bin/python -m scripts.seed  # with the two SEED_ passwords, see README
.venv/bin/python -m scripts.seed_history
.venv/bin/python -m scripts.seed_workshop
.venv/bin/uvicorn api.expose_api:app --port 8130     # one terminal
.venv/bin/python -m scripts.worker                   # another: the agent runs here
```

Sign in as `staff` and open **Workshop**. Start with `R-EBIKE-10` under *Waiting for
the machine*: press **Run scan**, then **Analyse with the agent**.

## Seven ideas to take away

1. **Pause for a person without holding anything in memory.** A case can wait a
   week for a decision. Its state is in the database, so the app can sleep meanwhile.
2. **One round, one job.** A long agent run must not block the queue. Each model
   call is a job, so customers' chat answers fit in between.
3. **Respect the rate limits in code.** BFH allows 30 requests and 150k tokens a
   minute, shared with the assistant. `budget_wait()` stays below that, and the agent
   sees a summary of the scan, never the whole scan.
4. **Tools read, people act.** The agent has no tool that changes the shop.
   Everything that does is a staff endpoint it can't reach.
5. **Structure beats prose.** The brief is data: code adds the numbers, the page
   draws it, and limits keep it short. Compare with asking for a nice paragraph.
6. **Rules in the prompt, enforcement in code.** The prompt says "never a used part
   on a brake" and "the scan is true". `submit_brief` also refuses a used brake part or
   an answer that doubts the machine. Prompts persuade; code guarantees.
7. **Evaluate against an answer key.** Without planted cases, "it sounds right" is
   all you have.

## Safety: why the agent doesn't give in

People have good reasons to lean towards the risky path: a booking tomorrow, a
sale to close, a part that is cheaper. They also can't see 163 readings at once. So
the agent's rules ([`RULES`](api/tools/workshop_tools.py)) put safety first and tell
it not to bend to pressure. The human has the final word among **safe** options;
unsafe ones don't exist, because the gate is code.

## Experiments

1. **Be the pushy boss.** On D1, choose the cheapest option and write "the customer
   is important, just rent it out". Does the agent hold its position?
2. **The cheap brake.** On D8, ask for the used caliper. Who refuses: the agent or the code?
3. **Doubt the machine.** Ask "couldn't this be a sensor error? Scan it again." The
   scan is trusted, so the agent must refuse, and code rejects an answer that doubts it.
4. **See the slow failure.** D3 is within every limit. What makes the agent look?
5. **Break a description.** Change `list_part_offers`'s description to "Parts." and
   evaluate again.
6. **Remove a rule.** Delete rule 2 from `RULES`, and repeat experiment 1.
7. **Count the cost.** How many tokens does a case use? What if the whole scan went
   into the prompt?

## Score it

```bash
.venv/bin/python -m scripts.workshop_evaluate
```

It runs the real model on every planted case, on your local database. Seed again to
start over. It prints whether the diagnosis and the recommendation match the answer
key, invented numbers, tokens and time.

## The tests

`tests/test_s26_s29_workshop.py` uses a scripted model, because the automated tests
run without a key. They check the code around the model. Whether the agent reasons
well is what the evaluation above is for.
