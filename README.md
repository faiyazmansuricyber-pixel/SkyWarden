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
to `.env`, seed the synthetic database, and start only on the loopback interface:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m scripts.seed
python -m uvicorn target_app.main:app --host 127.0.0.1 --port 8001
```

Run the app tests with `python -m pytest`. Reseed the local database with
`python -m scripts.reset`. Never commit `.env` or generated `data/`.
