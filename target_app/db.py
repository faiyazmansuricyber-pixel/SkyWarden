from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "skyvoyage.sqlite3"
PASSWORD_HASH_ITERATIONS = 600_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS agencies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    agency_id TEXT NOT NULL REFERENCES agencies(id),
    role TEXT NOT NULL CHECK (role IN ('admin', 'agent', 'subagent')),
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT,
    phone TEXT
);

CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS flights (
    id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_at TEXT NOT NULL,
    base_fare_cents INTEGER NOT NULL CHECK (base_fare_cents > 0),
    currency TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0)
);

CREATE TABLE IF NOT EXISTS holds (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    flight_id TEXT NOT NULL REFERENCES flights(id),
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 9),
    status TEXT NOT NULL CHECK (status IN ('active', 'used')),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    agency_id TEXT NOT NULL REFERENCES agencies(id),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id),
    flight_id TEXT NOT NULL REFERENCES flights(id),
    hold_id TEXT UNIQUE REFERENCES holds(id),
    traveler_name TEXT NOT NULL,
    passport_number TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 9),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0),
    total_price_cents INTEGER NOT NULL CHECK (total_price_cents > 0),
    status TEXT NOT NULL CHECK (status IN ('booked', 'paid', 'cancelled')),
    refund_amount_cents INTEGER NOT NULL DEFAULT 0 CHECK (refund_amount_cents >= 0),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS bookings_agency_idx
    ON bookings (agency_id, created_by_user_id);
CREATE INDEX IF NOT EXISTS bookings_flight_status_idx
    ON bookings (flight_id, status);
CREATE INDEX IF NOT EXISTS holds_flight_expiry_idx
    ON holds (flight_id, status, expires_at);

CREATE TABLE IF NOT EXISTS release_flags (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    release_version TEXT NOT NULL,
    flags_json TEXT NOT NULL
);
"""


def connect_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    with connect_db(db_path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            """
            INSERT OR IGNORE INTO release_flags (id, release_version, flags_json)
            VALUES (1, 'v3.0', '{}')
            """
        )


def read_release_flags(db_path: Path = DEFAULT_DB_PATH) -> tuple[str, dict[str, bool]]:
    with connect_db(db_path) as connection:
        row = connection.execute(
            "SELECT release_version, flags_json FROM release_flags WHERE id = 1"
        ).fetchone()

    if row is None:
        raise RuntimeError("The SkyVoyage release/flags row is missing.")

    flags = json.loads(row["flags_json"])
    if not isinstance(flags, dict) or any(
        not isinstance(name, str) or not isinstance(enabled, bool)
        for name, enabled in flags.items()
    ):
        raise ValueError("The SkyVoyage release flags must be a JSON object of booleans.")

    return row["release_version"], flags
