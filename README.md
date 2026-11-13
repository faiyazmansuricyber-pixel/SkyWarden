# SkyWarden

Agentic real-time DAST for travel platforms. Team Cyphers, VOYAGEHACK 4.0.
SkyWarden tests only the team's synthetic SkyVoyage mock app on `127.0.0.1`.
See [PLAN.md](PLAN.md) for the project specification and milestone order.

## Development setup

Use Python 3.12 (supported project versions: Python 3.11+).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

The checked-in `.env.example` contains fake local test credentials. To use them, copy it
to `.env` if needed, seed the synthetic database, and start both apps only on their
loopback interfaces:

```powershell
.\.venv\Scripts\Activate.ps1
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m scripts.seed
python -m uvicorn target_app.main:app --host 127.0.0.1 --port 8001
```

In a second terminal, start the local-only release/flag control app:

```powershell
.\.venv\Scripts\Activate.ps1
python -m target_app.admin
```

After both apps are running, deploy the vulnerable demo release with
`python scripts/deploy.py v3.1`. The admin app must be available; if the engine
webhook on `127.0.0.1:9000` is absent, the deploy script warns and continues.
The admin app is not an agent target. See [docs/VULNS.md](docs/VULNS.md) for the
synthetic vulnerability ground truth.

Run the app tests with `python -m pytest`. Reseed the local database with
`python -m scripts.reset`. Never commit `.env` or generated `data/`.

Generate the synthetic 90-day access log with about 50,000 records using
`python -m traffic.generate_logs`; it writes the ignored file
`data/access_logs.jsonl`.

Install the Playwright browser once with `python -m playwright install chromium`.
With the SkyVoyage app running on `127.0.0.1:8001` and the access log generated,
run `python -m scripts.recon` to crawl the seeded roles, probe the bounded local
route patterns through the safety gate, and write the inventory database,
redacted HAR files, and `data/openapi.json`.

## Dashboard

Install the UI dependencies once with `Set-Location ui; npm ci`. With the M3
inventory generated, start the read-only API in one terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 9000
```

In another terminal, run `.\scripts\start_ui.ps1` and open
`http://127.0.0.1:5173`. If M3 artifacts are unavailable, the API reports that
state explicitly; the dashboard never substitutes sample inventory.
