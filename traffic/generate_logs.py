from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "access_logs.jsonl"
DEFAULT_RECORD_COUNT = 50_000
RANDOM_SEED = 4_202_611
AGENCY_USERS = (
    ("admin", "agency_a"),
    ("agent", "agency_a"),
    ("subagent", "agency_a"),
    ("admin", "agency_b"),
    ("agent", "agency_b"),
)


@dataclass(frozen=True)
class TrafficEvent:
    method: str
    path: str
    status: int
    weight: int
    mobile_only: bool = False


NORMAL_EVENTS = (
    TrafficEvent("POST", "/api/v3/auth/login", 200, 8),
    TrafficEvent("GET", "/api/v3/search/flights", 200, 22),
    TrafficEvent("POST", "/api/v3/holds", 201, 9),
    TrafficEvent("POST", "/api/v3/bookings", 201, 10),
    TrafficEvent("GET", "/api/v3/bookings/agency_a-booking-001", 200, 15),
    TrafficEvent("POST", "/api/v3/bookings/agency_a-booking-001/pay", 200, 4),
    TrafficEvent("POST", "/api/v3/bookings/agency_a-booking-001/cancel", 200, 4),
    TrafficEvent("GET", "/api/v3/users/me", 200, 8),
    TrafficEvent("PATCH", "/api/v3/users/me", 200, 3),
    TrafficEvent(
        "GET", "/api/v3/bookings/agency_a-booking-001/invoice", 200, 3
    ),
    TrafficEvent("GET", "/api/m/v2/fares", 200, 6, mobile_only=True),
)

NOISE_EVENTS = (
    TrafficEvent("GET", "/health", 200, 4),
    TrafficEvent("GET", "/api/v3/not-a-route", 404, 3),
    TrafficEvent("GET", "/.well-known/security.txt", 404, 2),
    TrafficEvent("POST", "/wp-login.php", 404, 1),
)

WEB_USER_AGENTS = (
    "SkyVoyageWeb/3.0 Chrome",
    "SkyVoyageWeb/3.0 Firefox",
    "SkyVoyageWeb/3.0 Edge",
)
MOBILE_USER_AGENTS = (
    "SkyVoyageMobile/3.0 (Android)",
    "SkyVoyageMobile/3.0 (iPhone)",
)
SCANNER_USER_AGENTS = ("SyntheticScanner/1.0", "SyntheticAudit/1.0")


def _write_record(
    output: TextIO,
    timestamp: datetime,
    event: TrafficEvent,
    rng: random.Random,
) -> None:
    if event.mobile_only:
        role, agency = rng.choice(AGENCY_USERS)
        user_agent = rng.choice(MOBILE_USER_AGENTS)
    elif event.path == "/health":
        role, agency = "system", "none"
        user_agent = "SkyVoyageHealth/1.0"
    elif event in NOISE_EVENTS:
        role, agency = "anonymous", "none"
        user_agent = rng.choice(SCANNER_USER_AGENTS)
    elif event.path == "/api/v3/auth/login":
        role, agency = "anonymous", "none"
        user_agent = rng.choice(WEB_USER_AGENTS)
    else:
        role, agency = rng.choice(AGENCY_USERS)
        user_agent = rng.choice(WEB_USER_AGENTS)

    record = {
        "ts": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "method": event.method,
        "path": event.path,
        "status": event.status,
        "role": role,
        "agency": agency,
        "ua": user_agent,
        "bytes": rng.randint(128, 4096),
    }
    output.write(json.dumps(record, separators=(",", ":")) + "\n")


def generate_logs(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    record_count: int = DEFAULT_RECORD_COUNT,
    now: datetime | None = None,
) -> int:
    if record_count < 2:
        raise ValueError("record_count must be at least 2 to span the 90-day window.")

    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    end = end.astimezone(timezone.utc)
    start = end - timedelta(days=90)
    rng = random.Random(RANDOM_SEED)
    events = NORMAL_EVENTS + NOISE_EVENTS
    weights = [event.weight for event in events]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for index in range(record_count):
            ratio = index / (record_count - 1)
            timestamp = start + (end - start) * ratio
            event = rng.choices(events, weights=weights, k=1)[0]
            _write_record(output, timestamp, event, rng)

    return record_count


def main() -> None:
    count = generate_logs()
    print(f"Wrote {count} synthetic access log records to {DEFAULT_OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
