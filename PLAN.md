# PLAN.md — SkyWarden · Team Cyphers · VOYAGEHACK 4.0 · Agentic Real-Time DAST

> SkyWarden = our agent product. SkyVoyage = the mock travel platform we test it on.
> This file is the single source of truth for the coding agent (VS Code GitHub Copilot agent, Antigravity, or any other).
> Read it fully before every session. Work on ONE milestone at a time. Never start a later milestone early.

---

## 0. Agent rules (read first)

1. **Free tools only.** No paid services, no paid APIs. LLM = Google Gemini API free key (model name in `.env` as `GEMINI_MODEL`).
2. **Safety first.** The LLM never sends HTTP traffic. Every request goes through `safety/gate.py`. Breaking scope rules = disqualification in the hackathon.
3. **Targets are local only.** The only allowed target is our own mock app (`target_app/`) on `127.0.0.1`. Never scan any real or third-party host.
4. **Small steps.** One module per task. After each module: write tests, run them, fix, then `git commit`.
5. **No fake results.** The dashboard must show real engine output. No hardcoded findings. If something is mocked, say so in the code and in the README.
6. **Summarise briefly.** After each task, reply in chat with 3 to 5 lines: what was built, which files changed, and the command to run it. No changelog file is needed.
7. **Keep it simple.** Prefer plain Python and SQLite over extra frameworks. No Docker until M8.
8. If a requirement is unclear, ask the owner a short question instead of guessing.

---

## 1. Project in one paragraph

An autonomous security-agent loop for a B2B travel platform. On every deploy it **detects what changed, learns the app, plans targeted attacks, executes them safely, verifies each hit with a minimal proof, triages by business impact, raises a ticket, and retests after the fix**. It also builds an API inventory labelling endpoints **active / zombie / shadow** and generates an **OpenAPI spec**. A 3D dashboard shows all of this live.

Hackathon rounds: Prototype submission window **26 Nov to 24 Dec 2026** (10-slide PPT + GitHub code + explainer video). Finale **8 Jan 2027**.

---

## 2. Judging criteria (design for these)

| Weight | Criterion | What we do |
|---|---|---|
| 30% | Valid findings and severity | Deep on access control (IDOR) and business logic |
| 20% | Precision, low noise | Two-account verified proof; dedupe; drop unproven |
| 20% | Safety and scope | Gate: allowlist, rate limit, health pause, human approval, audit log |
| 10% | Speed after change | Test only what changed; show deploy-to-finding time |
| 10% | Report quality | Ticket: evidence, impact, severity, owner, fix; auto-retest |
| 10% | Discovery and inventory | Active/zombie/shadow + OpenAPI |

---

## 3. Tech stack (all free)

- **Python 3.11+**, FastAPI, httpx, pydantic, SQLite (sqlite3), NetworkX, pytest
- **Playwright** (Python) for role-based crawling + HAR capture
- **LangGraph** for the orchestrator (fallback: a simple state machine in plain Python)
- **Gemini API (free key)** for planning, business-flow tagging, severity rationale, fix text. Cache every LLM call in SQLite. Every LLM step has a deterministic fallback so the demo works offline.
- **Optional plug-ins:** Nuclei / ZAP wrappers for auth, injection, SSRF (design + stub only unless time allows)
- **UI:** React + Vite + TypeScript + Tailwind, `react-three-fiber` + `drei` (or `3d-force-graph`), Framer Motion, WebSocket
- **Tickets:** local JSON/Markdown + optional GitHub Issues API (free)

---

## 4. Repository layout

```
skywarden/
  PLAN.md
  README.md
  .env.example
  docs/            ARCHITECTURE.md, DEMO.md
  target_app/      SkyVoyage mock travel platform (FastAPI) + web portal + JS bundle
  traffic/         generate_logs.py -> data/access_logs.jsonl (90 days)
  scripts/         deploy.py, seed.py, reset.py
  engine/
    safety/        gate.py, rate_limiter.py, health.py, audit.py, vault.py, approvals.py
    kb/            db.py (SQLite), graph.py (NetworkX)
    recon/         crawler.py, js_routes.py, prober.py
    inventory/     classify.py, openapi_gen.py
    planner/       planner.py, llm.py (cache + fallback)
    executors/     base.py, idor.py, business_logic.py, plugins/ (stubs)
    verifier/      verify.py
    triage/        triage.py, owners.yaml, flow_weights.yaml
    report/        reporter.py, templates/
    retest/        retest.py
    orchestrator.py
  api/             FastAPI app + WebSocket event stream
  ui/              React dashboard
  tests/
  data/            (gitignored) sqlite db, logs, audit.jsonl
```

---

## 5. Target app: "SkyVoyage" (mock B2B travel platform)

Runs on `127.0.0.1:8001`. A separate admin control port `127.0.0.1:8002` (NOT in scope for agents) is used only by `scripts/deploy.py` to flip release flags.

### 5.1 Synthetic data and test accounts

- Agencies: **Agency A** and **Agency B** (synthetic names).
- Accounts (all fake, stored in `.env`/vault, never printed in logs):
  - `admin_a`, `agent_a`, `subagent_a` (Agency A)
  - `admin_b`, `agent_b` (Agency B)
- Auth: bearer token via `POST /api/v3/auth/login`.
- Seed ~30 bookings per agency with fake travellers (fake passport numbers like `X0000001`).

### 5.2 Endpoints (current release v3)

| Method | Path | Flow | Notes |
|---|---|---|---|
| POST | /api/v3/auth/login | auth | |
| GET | /api/v3/search/flights | search | read-only |
| POST | /api/v3/holds | hold | takes `qty` |
| POST | /api/v3/bookings | book | takes fare data |
| GET | /api/v3/bookings/{id} | book | proper agency check |
| POST | /api/v3/bookings/{id}/pay | pay | |
| POST | /api/v3/bookings/{id}/cancel | cancel/refund | |
| GET | /api/v3/users/me | account | |
| PATCH | /api/v3/users/me | account | |
| GET | /api/m/v2/fares | search | used ONLY by the mobile app (shadow) |

### 5.3 Planted vulnerabilities (keep a private `docs/VULNS.md` ground-truth list)

| ID | Class | Where | Description |
|---|---|---|---|
| B1 | Access control (IDOR) | GET /api/v3/bookings/{id}/invoice | **Introduced by deploy v3.1** (demo): returns any agency's invoice |
| B2 | Business logic | POST /api/v3/bookings | Server trusts client-sent `total_price` |
| B3 | Business logic | POST /api/v3/bookings/{id}/cancel | Can be called twice and refunds twice (state-changing: needs human approval) |
| B4 | Business logic | POST /api/v3/holds | Negative `qty` reduces total price |
| B5 | Auth / API hygiene | PATCH /api/v3/users/me | Mass assignment: `role` accepted, sub-agent can become admin |
| Z1 | Zombie | /api/v1/bookings/{id} | Old version still live, no auth, zero traffic in 90 days, exposes passport field |
| Z2 | Zombie | /api/v3/debug/config | Debug route left in production, returns config values (fake) |
| S1 | Shadow | /api/m/v2/fares | In traffic logs but not linked in web UI or JS bundle |

Each vuln has a feature flag `FIX_<ID>=1` so the **retest** can show a fix closing the finding.

### 5.4 Web portal

Small HTML/JS portal at `/` with login, search, hold, book, pay, cancel pages. It serves a JS bundle that references API routes (so the crawler and JS parser have something to find). The mobile-only and debug routes are deliberately NOT referenced.

### 5.5 Release simulation

`scripts/deploy.py v3.1`:
1. Flips flags on the admin port (adds B1).
2. Sends a deploy webhook `POST http://127.0.0.1:9000/webhook/deploy` with `{version, changed_files, timestamp}`.

---

## 6. Synthetic traffic logs

`traffic/generate_logs.py` writes `data/access_logs.jsonl` (90 days, ~50k lines):
`{ts, method, path, status, role, agency, ua, bytes}`

Rules so inventory has a ground truth:
- Normal v3 endpoints: steady traffic.
- `/api/m/v2/fares`: traffic present (mobile UA) but NOT in the web UI → **shadow**.
- `/api/v1/bookings/{id}` and `/api/v3/debug/config`: **zero** requests in the last 90 days → **zombie** (still respond).
- Add some noise: scanner hits, 404s, health checks.

---

## 7. Safety layer (BUILD THIS BEFORE ANY EXECUTOR)

`engine/safety/gate.py` exposes ONE function used by everything: `gate.send(request, risk, context) -> response`.

Checks, in order. Any failure raises `Blocked(reason)` and is audit-logged:
1. **Scope allowlist:** host must be `127.0.0.1:8001`; paths must match allowed prefixes; `/__admin` and port 8002 are always denied.
2. **Credential check:** only vault accounts; tokens never written to logs.
3. **Rate limit:** token bucket, default 5 req/s global and 2 req/s per endpoint (config in `.env`).
4. **Risk class:** `R0` read-only, `R1` state-changing on the test account's own resources, `R2` financial (refund/pay). `R2` requires **human approval** (UI button) before sending; `R1` requires explicit executor justification.
5. **Health monitor:** track latency and 5xx. If p95 latency > 3x baseline or 5xx rate > 20% over the last 20 requests, **pause all testing** and raise an alarm event.
6. **Kill switch:** `POST /api/control/pause` stops everything immediately.
7. **Audit log:** append-only `data/audit.jsonl` with every request/response summary (headers redacted), decision, reason, timestamp. Replayable.

Unit tests required: out-of-scope blocked, rate limit enforced, R2 blocked without approval, health pause triggers, secrets never in the log.

---

## 8. Agent loop (stages)

1. **Detect change** — triggers: deploy webhook; diff of JS bundle hash; diff of endpoint set seen in logs. Output: list of changed/new endpoints.
2. **Recon / learn** — Playwright crawl as each role; capture HAR; parse JS bundles for routes (regex + AST); probe version/naming patterns (`/v1/`, `/old/`, `/internal/`, `/test/`, `/beta/`, `/debug/`) through the gate. Store endpoints, params, roles, flows in the **knowledge graph** (SQLite + NetworkX).
3. **Inventory** — compare KB with 90-day logs. Label each endpoint: `active`, `zombie` (responds, no real traffic), `shadow` (in traffic, not in the discovered map). For each zombie/shadow record: last real traffic date, reachable without auth, data exposed, differences vs current version, likely owner (`owners.yaml`), recommendation (decommission / restrict / update). Export OpenAPI 3 to `data/openapi.json`.
4. **Plan attacks** — for changed endpoints only. Gemini returns a **TestPlan JSON** (validated by pydantic schema: endpoint, vuln_class, steps, risk_class, justification). Fallback: deterministic rules (ID in path -> IDOR test; price/qty field -> logic test; `role` field on PATCH -> mass assignment).
5. **Execute safely** — specialist executors build requests from the TestPlan and send ONLY via `gate.send`.
   - `idor.py`: Agency A account requests Agency B resource; control requests as owner.
   - `business_logic.py`: tampered price, negative quantity, double cancel/refund, skipped payment step.
6. **Verify** — replay a minimal proof with fresh requests: (a) owner request returns resource, (b) attacker request returns the same resource data, (c) negative control (attacker on own resource) behaves normally. A finding is only `confirmed` if it reproduces twice and with two accounts. Store redacted evidence only.
7. **Triage** — dedupe by `(class, endpoint template, parameter)`. Severity = exploitability x business weight (`flow_weights.yaml`: search 1, hold 2, book 3, pay 5, refund 5, auth/admin 5; PII multiplier 1.5). Owner from `owners.yaml`. High severity -> `needs_human_review`.
8. **Report** — ticket (JSON + Markdown): title, severity, business impact, affected endpoint, evidence, steps to reproduce, owner, suggested fix. Output to `data/tickets/`; optionally GitHub Issues.
9. **Retest** — after `FIX_<ID>=1`, rerun the stored proof; mark `fixed` or `still_vulnerable`.

All stages emit events (see section 9).

---

## 9. API and event stream (`api/`, port 9000)

REST:
- `POST /webhook/deploy`
- `GET /api/graph` (nodes/edges with status), `GET /api/endpoints`, `GET /api/findings`, `GET /api/findings/{id}`
- `GET /api/inventory`, `GET /api/openapi`
- `GET /api/safety/status`, `POST /api/control/pause|resume`
- `GET /api/approvals`, `POST /api/approvals/{id}/approve|deny`
- `POST /api/retest/{finding_id}`
- `POST /api/demo/deploy` (runs `scripts/deploy.py` for the UI button)

WebSocket `/ws` events (JSON): `deploy_detected`, `endpoint_discovered`, `inventory_labelled`, `test_planned`, `request_sent`, `request_blocked`, `approval_required`, `finding_candidate`, `finding_confirmed`, `finding_dropped`, `ticket_created`, `retest_result`, `health_alarm`, `metrics` (includes `deploy_to_finding_seconds`).

---

## 10. Dashboard UI (`ui/`)

Dark "mission control" look. **Everything is driven by the API/WebSocket, no hardcoded data.**

Panels:
1. **3D API map (hero):** one glowing node per endpoint; colors: active = teal, zombie = amber, shadow = purple/red. Edges = flows. Click a node for details. During a test, an animated pulse travels along the attack path. A new endpoint from a deploy appears with an animation.
2. **Big "Deploy v3.1" button** that calls `/api/demo/deploy`. This runs the full loop live.
3. **Live agent timeline:** stage progress + streaming events.
4. **Safety panel:** allowed vs blocked counts, rate meter, health status, kill switch, human-approval pop-up for R2 tests.
5. **Findings list + detail:** severity badge, evidence, two-account proof view, ticket preview, **Retest** button.
6. **Inventory table:** zombie/shadow with last traffic, auth exposure, owner, recommended action; "Download OpenAPI".
7. **Metrics bar:** deploy-to-finding time, requests sent, false positives dropped.

Performance rule: the 3D scene must stay smooth on a laptop with an RTX 3050 (limit nodes to ~100, no heavy post-processing).

---

## 11. Milestones (one at a time; do not skip order)

Dates are targets. Submit by **22 Dec** to keep a buffer before the 24 Dec 11:59 PM IST deadline.

| # | Dates | Deliverable | Acceptance test |
|---|---|---|---|
| M0 | 13–15 Nov | Repo, venv, `.env.example`, folder layout, pytest runs | `pytest` passes (empty) |
| M1 | 16–20 Nov | Target app + seed data + web portal + planted bugs + flags + `deploy.py` | Manual curl proves B1–B5 exist; flags fix them |
| M1b | 20–21 Nov | Traffic log generator | Logs show shadow/zombie ground truth |
| M2 | 21–24 Nov | **Safety layer** + tests | All safety tests pass |
| M3 | 25 Nov–1 Dec | Recon + KB + inventory + OpenAPI | Finds all 8 planted items correctly labelled |
| M4 | 2–8 Dec | Planner + IDOR + business-logic executors + verifier | Confirms B1–B5, drops a seeded false positive |
| M5 | 9–12 Dec | Triage + report + retest + orchestrator + deploy trigger | `deploy.py v3.1` ends with a ticket; retest closes it |
| M6 | 12–14 Dec | API + WebSocket events | Events stream during a full run |
| M7 | 14–20 Dec | 3D dashboard | Full live demo from the UI button |
| M8 | 20–22 Dec | README, ARCHITECTURE, Docker Compose (optional), 10-slide deck, explainer video, submission | Fresh clone runs by README steps |
| M9 | 22–24 Dec | Buffer, bug fixes, submit | Submitted |

---

## 12. Definition of done (demo script, 60–90 seconds)

1. Open dashboard: 3D map shows active, zombie and shadow nodes.
2. Click **Deploy v3.1**: deploy detected, new invoice node appears.
3. Agent plans one targeted IDOR test; safety panel shows requests allowed.
4. Finding is verified with two-account proof; ticket appears with severity Critical and owner.
5. A risky refund test asks for **human approval**; click approve.
6. Show the inventory: zombie and shadow APIs with recommended actions; download OpenAPI.
7. Toggle `FIX_B1`, press **Retest**: finding closes.
8. Show the audit log replay and the metric "deploy to finding" time.

---

## 13. Prompt template for the coding agent (copy per task)

```
Read PLAN.md fully. We are on milestone <Mx>. Implement ONLY <module/task>.
Follow the agent rules in section 0 and the spec in section <n>.
Create tests, run them, fix failures, then summarise in chat what you built and how to run it.
Do not touch other milestones.
```

---

## 14. Do-not list

- No scanning of anything outside `127.0.0.1:8001`.
- No destructive, DoS, or bulk-extraction tests.
- No real personal data, real cards, or real passports. Synthetic only.
- No secrets in git (`.env` is gitignored).
- No hardcoded UI data or fake findings.

## 15. Decisions log

- Python support is 3.11+; M0 uses Python 3.12.
- M0 includes one minimal passing pytest test.
- `.gitignore` excludes `data/`, `.venv/`, `node_modules/`, `__pycache__/`, and `.env`.
- `.env.example` uses empty `GEMINI_API_KEY` and `GEMINI_MODEL` values, clearly fake test credentials, and `RATE_LIMIT_GLOBAL_RPS` / `RATE_LIMIT_PER_ENDPOINT_RPS`.
- For M3 inventory, B1–B5 endpoints are active when normally reachable; Z1 and Z2 are zombie; S1 is shadow.
- M2 uses an explicit CLI/test provider for R2 approval; API/UI approval is added in M6/M7.
- `FIX_B1`–`FIX_B5` close their bugs; `FIX_Z1` and `FIX_Z2` make their routes return 404; `FIX_S1` exposes the route in the web portal JavaScript bundle.
- For M4, negative quantity and price tampering are R1; double refund is R2. One approval covers both replays of a plan. Each state-changing test creates a fresh booking with a test account. Only `scripts/reset.py` may reset the database; the agent must not.
- M2 health uses a 100 ms latency baseline and evaluates its thresholds on a 20-response window; R2 CLI/test approval requires a `plan_id` and is cached per plan.
- Until M5 creates triage ownership data, M3 inventory ownership mappings live in `engine/inventory/owners.yaml`.
- M6's first API slice is read-only and exposes only the requested graph, inventory, and OpenAPI GET routes; it returns an explicit 503 when M3 artifacts are absent and never creates or seeds them. CORS is limited to localhost and 127.0.0.1 on Vite's port 5173.
- Since the M3 endpoint schema has no flow field, M6 derives flow from the endpoint path; unrecognized paths are labelled `unknown` rather than supplied with UI fallback data.
- M7a renders map and inventory data only from the read-only API; unimplemented timeline, safety, findings, and deploy panels remain visibly labelled placeholders and do not simulate activity.
