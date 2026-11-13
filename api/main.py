from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine.kb.db import DEFAULT_DB_PATH
from engine.inventory.openapi_gen import DEFAULT_OPENAPI_PATH


def _unavailable(message: str) -> HTTPException:
    return HTTPException(status_code=503, detail=message)


def _read_knowledge_base(database_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not database_path.is_file():
        raise _unavailable("M3 inventory is unavailable; run the local recon pipeline first.")
    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(database_uri, uri=True)
    except sqlite3.Error as error:
        raise _unavailable("M3 knowledge base could not be opened read-only.") from error
    connection.row_factory = sqlite3.Row
    try:
        endpoint_rows = connection.execute(
            "SELECT * FROM endpoints ORDER BY path, method"
        ).fetchall()
        edge_rows = connection.execute(
            """
            SELECT source_method, source_path, target_method, target_path, relation
            FROM edges
            ORDER BY source_path, target_path, relation
            """
        ).fetchall()
    except sqlite3.Error as error:
        raise _unavailable("M3 knowledge base does not contain inventory data.") from error
    finally:
        connection.close()

    endpoints: list[dict[str, Any]] = []
    try:
        for row in endpoint_rows:
            endpoints.append(
                {
                    "method": row["method"],
                    "path": row["path"],
                    "classification": row["classification"],
                    "reachable": bool(row["reachable"]),
                    "status_code": row["status_code"],
                    "last_traffic": row["last_traffic"],
                    "auth_required": (
                        None
                        if row["auth_required"] is None
                        else bool(row["auth_required"])
                    ),
                    "data_exposed": json.loads(row["data_exposed"]),
                    "owner": row["owner"],
                    "recommendation": row["recommendation"],
                    "roles": json.loads(row["roles"]),
                    "sources": json.loads(row["sources"]),
                }
            )
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise _unavailable("M3 knowledge base contains invalid inventory records.") from error

    edges = [
        {
            "source": f"{row['source_method'].upper()} {row['source_path']}",
            "target": f"{row['target_method'].upper()} {row['target_path']}",
            "flow": row["relation"],
        }
        for row in edge_rows
    ]
    return endpoints, edges


def _flow_for_path(path: str) -> str:
    if "/auth/" in path:
        return "auth"
    if "/search/" in path or path.endswith("/fares"):
        return "search"
    if path.endswith("/holds"):
        return "hold"
    if path.endswith("/pay"):
        return "pay"
    if path.endswith("/cancel"):
        return "cancel/refund"
    if path.endswith("/invoice") or "/bookings" in path:
        return "booking"
    if "/users/" in path:
        return "account"
    return "unknown"


def _read_openapi(openapi_path: Path) -> dict[str, Any]:
    if not openapi_path.is_file():
        raise _unavailable("M3 OpenAPI output is unavailable; run the local recon pipeline first.")
    try:
        document = json.loads(openapi_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _unavailable("M3 OpenAPI output could not be read.") from error
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise _unavailable("M3 OpenAPI output is not a valid document.")
    return document


def create_app(
    database_path: Path = DEFAULT_DB_PATH,
    openapi_path: Path = DEFAULT_OPENAPI_PATH,
) -> FastAPI:
    app = FastAPI(
        title="SkyWarden dashboard API",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/graph")
    def graph() -> dict[str, list[dict[str, Any]]]:
        endpoints, edges = _read_knowledge_base(database_path)
        nodes = [
            {
                "id": f"{endpoint['method'].upper()} {endpoint['path']}",
                "method": endpoint["method"],
                "path": endpoint["path"],
                "status": endpoint["classification"],
                "flow": _flow_for_path(endpoint["path"]),
                "auth_required": endpoint["auth_required"],
                "last_traffic": endpoint["last_traffic"],
                "owner": endpoint["owner"],
                "recommendation": endpoint["recommendation"],
                "data_exposed": endpoint["data_exposed"],
                "reachable": endpoint["reachable"],
            }
            for endpoint in endpoints
        ]
        return {"nodes": nodes, "edges": edges}

    @app.get("/api/inventory")
    def inventory() -> dict[str, list[dict[str, Any]]]:
        endpoints, _ = _read_knowledge_base(database_path)
        return {"items": endpoints}

    @app.get("/api/openapi")
    def openapi_document() -> dict[str, Any]:
        return _read_openapi(openapi_path)

    return app


app = create_app()
