# SkyWarden status

- Current milestone: M3 complete; M4 is next.
- M0, M1A, M1B, M1C, M1b, M2, and M3 are complete.
- M1B has flag-gated vulnerabilities, loopback admin controls, deploy/reset
  scripts, and ground-truth tests. M1C serves a content-hashed JavaScript bundle;
  M1b generates 50,000 synthetic access records across 90 days.
- M2 adds the scoped safety gate, vault, token-bucket rate limits, health pause,
  redacted append-only audit log, and cached CLI/test R2 approvals.
- M3 adds gated role-based crawling and probing, redacted HAR capture, a SQLite
  and NetworkX endpoint graph, active/zombie/shadow inventory, and OpenAPI output.
- Last test result: `python -m pytest -q` — 29 passed (Python 3.12).
