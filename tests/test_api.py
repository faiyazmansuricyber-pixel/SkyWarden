from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from engine.kb.db import KnowledgeBase


def test_read_only_api_serves_m3_inventory_graph_and_openapi(tmp_path: Path) -> None:
    database_path = tmp_path / "knowledge.sqlite3"
    knowledge_base = KnowledgeBase(database_path)
    records = (
        {
            "method": "GET",
            "path": "/api/v3/bookings/{id}/invoice",
            "classification": "active",
            "reachable": True,
            "status_code": 200,
            "last_traffic": "2026-11-12T12:00:00+00:00",
            "auth_required": True,
            "data_exposed": ["traveler_name"],
            "owner": "Booking platform team",
            "recommendation": "Monitor usage.",
            "roles": ["agent"],
            "sources": ["traffic"],
        },
        {
            "method": "GET",
            "path": "/api/v1/bookings/{id}",
            "classification": "zombie",
            "reachable": True,
            "status_code": 200,
            "last_traffic": None,
            "auth_required": False,
            "data_exposed": ["passport_number"],
            "owner": "Legacy platform team",
            "recommendation": "Decommission.",
            "roles": [],
            "sources": ["safety-gated probe"],
        },
    )
    for record in records:
        knowledge_base.upsert_endpoint(record)
    knowledge_base.add_edge(
        "GET",
        "/api/v3/bookings/{id}",
        "GET",
        "/api/v3/bookings/{id}/invoice",
        "observed_role_flow",
    )

    openapi_document = {
        "openapi": "3.0.3",
        "info": {"title": "SkyVoyage discovered API", "version": "3.0"},
        "paths": {"/api/v3/bookings/{id}/invoice": {"get": {}}},
    }
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(openapi_document), encoding="utf-8")
    app = create_app(database_path, openapi_path)

    with TestClient(app) as client:
        graph_response = client.get("/api/graph")
        inventory_response = client.get("/api/inventory")
        openapi_response = client.get(
            "/api/openapi",
            headers={"Origin": "http://127.0.0.1:5173"},
        )

    assert graph_response.status_code == 200
    graph_data = graph_response.json()
    invoice = next(node for node in graph_data["nodes"] if node["status"] == "active")
    assert invoice["flow"] == "booking"
    assert invoice["auth_required"] is True
    assert invoice["last_traffic"] == "2026-11-12T12:00:00+00:00"
    assert graph_data["edges"] == [
        {
            "source": "GET /api/v3/bookings/{id}",
            "target": "GET /api/v3/bookings/{id}/invoice",
            "flow": "observed_role_flow",
        }
    ]
    assert inventory_response.status_code == 200
    assert len(inventory_response.json()["items"]) == 2
    assert openapi_response.json() == openapi_document
    assert openapi_response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_api_reports_missing_m3_artifacts_without_creating_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing.sqlite3"
    openapi_path = tmp_path / "missing-openapi.json"
    with TestClient(create_app(database_path, openapi_path)) as client:
        graph_response = client.get("/api/graph")
        openapi_response = client.get("/api/openapi")

    assert graph_response.status_code == 503
    assert openapi_response.status_code == 503
    assert not database_path.exists()
    assert not openapi_path.exists()


def test_api_exposes_swagger_docs_and_schema(tmp_path: Path) -> None:
    app = create_app(tmp_path / "knowledge.sqlite3", tmp_path / "openapi.json")

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        schema_response = client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert "text/html" in docs_response.headers["content-type"]
    assert schema_response.status_code == 200
    assert set(schema_response.json()["paths"]) == {
        "/api/graph",
        "/api/inventory",
        "/api/openapi",
    }
