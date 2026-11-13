from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "knowledge.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS endpoints (
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    classification TEXT NOT NULL,
    reachable INTEGER NOT NULL,
    status_code INTEGER,
    last_traffic TEXT,
    auth_required INTEGER,
    data_exposed TEXT NOT NULL,
    owner TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    roles TEXT NOT NULL,
    sources TEXT NOT NULL,
    PRIMARY KEY (method, path)
);

CREATE TABLE IF NOT EXISTS edges (
    source_method TEXT NOT NULL,
    source_path TEXT NOT NULL,
    target_method TEXT NOT NULL,
    target_path TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (source_method, source_path, target_method, target_path, relation)
);
"""


class KnowledgeBase:
    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def upsert_endpoint(self, endpoint: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO endpoints (
                    method, path, classification, reachable, status_code,
                    last_traffic, auth_required, data_exposed, owner,
                    recommendation, roles, sources
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(method, path) DO UPDATE SET
                    classification = excluded.classification,
                    reachable = excluded.reachable,
                    status_code = excluded.status_code,
                    last_traffic = excluded.last_traffic,
                    auth_required = excluded.auth_required,
                    data_exposed = excluded.data_exposed,
                    owner = excluded.owner,
                    recommendation = excluded.recommendation,
                    roles = excluded.roles,
                    sources = excluded.sources
                """,
                (
                    endpoint["method"],
                    endpoint["path"],
                    endpoint["classification"],
                    int(endpoint["reachable"]),
                    endpoint.get("status_code"),
                    endpoint.get("last_traffic"),
                    (
                        None
                        if endpoint.get("auth_required") is None
                        else int(endpoint["auth_required"])
                    ),
                    json.dumps(endpoint.get("data_exposed", []), sort_keys=True),
                    endpoint["owner"],
                    endpoint["recommendation"],
                    json.dumps(endpoint.get("roles", []), sort_keys=True),
                    json.dumps(endpoint.get("sources", []), sort_keys=True),
                ),
            )

    def add_edge(
        self,
        source_method: str,
        source_path: str,
        target_method: str,
        target_path: str,
        relation: str = "navigates_to",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO edges (
                    source_method, source_path, target_method, target_path, relation
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (source_method, source_path, target_method, target_path, relation),
            )

    def endpoints(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM endpoints ORDER BY path, method"
            ).fetchall()
        return [
            {
                **dict(row),
                "reachable": bool(row["reachable"]),
                "auth_required": (
                    None if row["auth_required"] is None else bool(row["auth_required"])
                ),
                "data_exposed": json.loads(row["data_exposed"]),
                "roles": json.loads(row["roles"]),
                "sources": json.loads(row["sources"]),
            }
            for row in rows
        ]

    def edges(self) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_method, source_path, target_method, target_path, relation
                FROM edges
                ORDER BY source_path, target_path, relation
                """
            ).fetchall()
        return [dict(row) for row in rows]
