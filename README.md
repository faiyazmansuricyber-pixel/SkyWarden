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

Copy `.env.example` to `.env` for local configuration. Never commit `.env` or generated `data/`.
