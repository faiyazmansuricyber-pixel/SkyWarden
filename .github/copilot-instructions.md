# SkyWarden project rules

- Always read PLAN.md before starting; work on one milestone at a time; summarise in chat at the end of each task.
- Use free tools and services only; use the free Gemini API tier.
- The LLM must never send HTTP traffic. Route every target request through `engine/safety/gate.py`.
- Test only the owned SkyVoyage mock app at `127.0.0.1:8001`; never scan real or third-party hosts.
- Never send requests to targets outside scope; honor the safety gate, approvals, rate limits, and kill switch.
- Make one small module change per task. Add tests, run them, fix failures, then commit.
- Never show fake findings or hardcode dashboard data. Label any mock behavior in code and README.
- Prefer simple Python and SQLite; do not add Docker before M8.
- Ask the owner when a requirement is unclear; do not guess.
- Use synthetic data only. Never use real personal data, cards, or passports.
- Do not run destructive, denial-of-service, or bulk-extraction tests.
- Never commit secrets. Keep `.env` and generated `data/` out of git.
