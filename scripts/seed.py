from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from target_app.db import (
    DEFAULT_DB_PATH,
    DEFAULT_FIX_FLAGS,
    PASSWORD_HASH_ITERATIONS,
    connect_db,
    initialize_database,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
ACCOUNT_SPECS = (
    ("TEST_ADMIN_A", "admin_a", "agency_a", "admin", "Admin A"),
    ("TEST_AGENT_A", "agent_a", "agency_a", "agent", "Agent A"),
    ("TEST_SUBAGENT_A", "subagent_a", "agency_a", "subagent", "Subagent A"),
    ("TEST_ADMIN_B", "admin_b", "agency_b", "admin", "Admin B"),
    ("TEST_AGENT_B", "agent_b", "agency_b", "agent", "Agent B"),
)
FLIGHT_SPECS = (
    ("SV100", "LHR", "JFK", 52000),
    ("SV101", "JFK", "LHR", 49500),
    ("SV200", "SFO", "LHR", 61000),
    ("SV201", "LHR", "SFO", 60500),
    ("SV300", "DXB", "SIN", 33000),
    ("SV301", "SIN", "DXB", 32500),
)
def _read_environment() -> Mapping[str, str]:
    load_dotenv(ROOT_DIR / ".env", override=False)
    load_dotenv(ROOT_DIR / ".env.example", override=False)
    return os.environ


def _read_account_values(
    environ: Mapping[str, str],
) -> list[tuple[str, str, str, str, str, str, bytes, bytes]]:
    accounts = []
    for prefix, default_username, agency_id, role, display_name in ACCOUNT_SPECS:
        username = environ.get(f"{prefix}_USERNAME", default_username).strip()
        password = environ.get(f"{prefix}_PASSWORD", "")
        if not username or not password:
            raise ValueError(
                f"Set {prefix}_USERNAME and {prefix}_PASSWORD in .env before seeding."
            )
        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PASSWORD_HASH_ITERATIONS,
        )
        accounts.append(
            (
                username,
                agency_id,
                role,
                display_name,
                f"{username}@example.invalid",
                None,
                salt,
                password_hash,
            )
        )
    return accounts


def _insert_flights(connection: sqlite3.Connection) -> None:
    depart_at = datetime.now(timezone.utc) + timedelta(days=14)
    connection.executemany(
        """
        INSERT INTO flights (
            id, origin, destination, depart_at, base_fare_cents, currency, capacity
        ) VALUES (?, ?, ?, ?, ?, 'USD', 200)
        """,
        [
            (
                flight_id,
                origin,
                destination,
                (depart_at + timedelta(hours=index * 3)).isoformat(),
                fare,
            )
            for index, (flight_id, origin, destination, fare) in enumerate(FLIGHT_SPECS)
        ],
    )


def _insert_bookings(connection: sqlite3.Connection) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    account_ids = {
        (row["agency_id"], row["role"]): row["id"]
        for row in connection.execute("SELECT id, agency_id, role FROM users")
    }
    rows = []
    passport_number = 1
    for agency_id, usernames in (
        ("agency_a", ("admin", "agent", "subagent")),
        ("agency_b", ("admin", "agent")),
    ):
        for booking_number in range(30):
            flight_id, _, _, unit_price_cents = FLIGHT_SPECS[
                booking_number % len(FLIGHT_SPECS)
            ]
            quantity = booking_number % 3 + 1
            role = usernames[booking_number % len(usernames)]
            rows.append(
                (
                    f"{agency_id}-booking-{booking_number + 1:03d}",
                    agency_id,
                    account_ids[(agency_id, role)],
                    flight_id,
                    f"Synthetic Traveller {agency_id[-1].upper()}-{booking_number + 1:02d}",
                    f"X{passport_number:07d}",
                    quantity,
                    unit_price_cents,
                    unit_price_cents * quantity,
                    created_at,
                )
            )
            passport_number += 1

    connection.executemany(
        """
        INSERT INTO bookings (
            id, agency_id, created_by_user_id, flight_id, traveler_name,
            passport_number, quantity, unit_price_cents, total_price_cents,
            status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'booked', ?)
        """,
        rows,
    )


def seed_database(
    db_path: Path = DEFAULT_DB_PATH,
    environ: Mapping[str, str] | None = None,
    reset_existing: bool = False,
) -> None:
    accounts = _read_account_values(environ if environ is not None else _read_environment())
    initialize_database(db_path)

    with connect_db(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if reset_existing:
            for table in (
                "tokens",
                "bookings",
                "holds",
                "flights",
                "users",
                "agencies",
            ):
                connection.execute(f"DELETE FROM {table}")
            connection.execute(
                "UPDATE release_flags SET release_version = 'v3.0', flags_json = ? WHERE id = 1",
                (json.dumps(DEFAULT_FIX_FLAGS, sort_keys=True),),
            )
        elif connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
            raise RuntimeError("Database is already seeded; use scripts.reset to reseed it.")

        connection.executemany(
            "INSERT OR IGNORE INTO agencies (id, name) VALUES (?, ?)",
            (("agency_a", "Agency A"), ("agency_b", "Agency B")),
        )
        connection.executemany(
            """
            INSERT INTO users (
                username, agency_id, role, display_name, email, phone,
                password_salt, password_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            accounts,
        )
        _insert_flights(connection)
        _insert_bookings(connection)


def main() -> None:
    try:
        seed_database()
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Seeded synthetic SkyVoyage data in {DEFAULT_DB_PATH}.")


if __name__ == "__main__":
    main()
