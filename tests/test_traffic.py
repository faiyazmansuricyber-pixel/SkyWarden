from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from traffic.generate_logs import DEFAULT_RECORD_COUNT, generate_logs


def test_generated_logs_preserve_inventory_ground_truth(tmp_path: Path) -> None:
    end = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    log_path = tmp_path / "access_logs.jsonl"
    count = generate_logs(log_path, now=end)
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert count == DEFAULT_RECORD_COUNT
    assert len(records) == DEFAULT_RECORD_COUNT
    assert set(records[0]) == {
        "ts",
        "method",
        "path",
        "status",
        "role",
        "agency",
        "ua",
        "bytes",
    }

    timestamps = [
        datetime.fromisoformat(record["ts"].replace("Z", "+00:00"))
        for record in records
    ]
    assert (max(timestamps) - min(timestamps)).total_seconds() == 90 * 24 * 60 * 60

    counts = Counter(record["path"] for record in records)
    for path in (
        "/api/v3/auth/login",
        "/api/v3/search/flights",
        "/api/v3/holds",
        "/api/v3/bookings",
        "/api/v3/users/me",
    ):
        assert counts[path] > 1000

    month_windows = Counter()
    start = min(timestamps)
    window_seconds = 30 * 24 * 60 * 60
    for record, timestamp in zip(records, timestamps):
        if record["path"] == "/api/v3/search/flights":
            window = min(
                2,
                int((timestamp - start).total_seconds() / window_seconds),
            )
            month_windows[window] += 1
    assert set(month_windows) == {0, 1, 2}
    assert min(month_windows.values()) > 3000

    mobile_fares = [row for row in records if row["path"] == "/api/m/v2/fares"]
    assert mobile_fares
    assert all(
        "mobile" in row["ua"].lower() or "android" in row["ua"].lower()
        or "iphone" in row["ua"].lower()
        for row in mobile_fares
    )
    assert not any(row["path"].startswith("/api/v1/bookings/") for row in records)
    assert not any(row["path"] == "/api/v3/debug/config" for row in records)
    assert any(row["status"] == 404 for row in records)
    assert any(row["ua"] in {"SyntheticScanner/1.0", "SyntheticAudit/1.0"} for row in records)
