# SkyWarden status

- Current milestone: M7a dashboard complete; no later milestone started.
- M0, M1A, M1B, M1C, M1b, M2, M3, M6 API, and M7a UI are complete.
- M1B provides flag-gated vulnerabilities and local admin controls; M1C serves
  the content-hashed portal bundle; M1b creates synthetic 90-day traffic.
- M2 provides the scoped safety gate, vault, rate limits, health pause, redacted
  audit log, and CLI/test R2 approvals.
- M3 provides gated crawling/probing, redacted HAR, the SQLite/NetworkX graph,
  active/zombie/shadow inventory, and OpenAPI generation.
- M6 exposes read-only graph, inventory, and OpenAPI GET routes with local-only
  dev CORS. M3 runtime artifacts are absent from this checkout; the API returns
  503 until recon generates them, without creating fallback data.
- M7a provides the API-backed endpoint map, inventory table, endpoint details,
  OpenAPI download, loading/error states, and clearly labelled unconnected
  placeholders. It uses no sample inventory or findings.
- Last test result: `python -m pytest -q` — 31 passed (Python 3.12);
  `npm run build` in `ui/` succeeded. The lazy-loaded map chunk exceeds Vite's
  500 kB advisory threshold (963 kB minified, 256 kB gzip).
