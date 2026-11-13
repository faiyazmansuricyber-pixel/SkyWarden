# SkyWarden status

- Current milestone: M6 API slice complete; M7a UI is next.
- M0, M1A, M1B, M1C, M1b, M2, M3, and the M6 read-only API slice are complete.
- M1B provides flag-gated vulnerabilities and local admin controls; M1C serves
  the content-hashed portal bundle; M1b creates synthetic 90-day traffic.
- M2 provides the scoped safety gate, vault, rate limits, health pause, redacted
  audit log, and CLI/test R2 approvals.
- M3 provides gated crawling/probing, redacted HAR, the SQLite/NetworkX graph,
  active/zombie/shadow inventory, and OpenAPI generation.
- M6 exposes read-only graph, inventory, and OpenAPI GET routes with local-only
  dev CORS. M3 runtime artifacts are absent from this checkout; the API returns
  503 until the recon pipeline generates them, without creating fallback data.
- Last test result: `python -m pytest -q` — 31 passed (Python 3.12).
