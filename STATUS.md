# SkyWarden status

- Current milestone: M1b complete; M2 is next.
- M0, M1A, M1B, M1C, and M1b are complete. M1B has flag-gated vulnerabilities,
  loopback admin controls, deploy/reset scripts, and ground-truth tests.
- M1C serves a content-hashed JavaScript bundle; `FIX_S1` adds the mobile fares
  reference, while the debug route is never included.
- M1b generates 50,000 synthetic access records across 90 days; mobile fares
  have mobile user agents and both zombie routes have zero traffic.
- Last test result: `python -m pytest -q` — 21 passed (Python 3.12).
