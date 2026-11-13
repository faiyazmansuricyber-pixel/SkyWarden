from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from engine.inventory.classify import load_traffic
from engine.kb.db import KnowledgeBase
from engine.kb.graph import EndpointGraph
from engine.recon.js_routes import extract_routes
from engine.recon.prober import build_probe_candidates
from engine.recon.pipeline import run_recon_inventory
from engine.safety.audit import AuditLog
from engine.safety.gate import SafetyGate
from engine.safety.health import HealthMonitor
from engine.safety.rate_limiter import RateLimiter
from engine.safety.vault import Vault, VaultAccount
from scripts.seed import ACCOUNT_SPECS, seed_database
from target_app.db import connect_db
from target_app.main import create_app


def _vault() -> tuple[Vault, dict[str, str]]:
    accounts = {}
    environment = {}
    for prefix, username, agency, role, _ in ACCOUNT_SPECS:
        password = f"synthetic-{username}-password"
        environment[f"{prefix}_USERNAME"] = username
        environment[f"{prefix}_PASSWORD"] = password
        accounts[username] = VaultAccount(username, password, agency, role)
    return Vault(accounts), environment


def test_js_route_extraction_and_probe_prefixes() -> None:
    source = """
      const invoice = "/api/v3/bookings/{id}/invoice";
      request(`/api/v3/bookings/${encodeURIComponent(id)}/cancel`);
      const mobile = "/api/m/v2/fares";
    """
    routes = extract_routes(source)
    assert "/api/v3/bookings/{id}/invoice" in routes
    assert "/api/v3/bookings/{id}/cancel" in routes
    assert "/api/m/v2/fares" in routes

    candidates = build_probe_candidates(
        ["/api/v3/bookings/agency_a-booking-001"]
    )
    assert {
        "/api/v1/bookings/agency_a-booking-001",
        "/api/old/bookings/agency_a-booking-001",
        "/api/internal/bookings/agency_a-booking-001",
        "/api/test/bookings/agency_a-booking-001",
        "/api/beta/bookings/agency_a-booking-001",
        "/api/debug/bookings/agency_a-booking-001",
        "/api/v3/debug/config",
        "/api/m/v2/fares",
    }.issubset(candidates)


def test_recon_pipeline_labels_planted_items_and_writes_openapi(
    tmp_path: Path,
) -> None:
    vault, environment = _vault()
    target_db = tmp_path / "skyvoyage.sqlite3"
    seed_database(target_db, environ=environment)
    with connect_db(target_db) as connection:
        connection.execute(
            "UPDATE release_flags SET release_version = 'v3.1' WHERE id = 1"
        )
    target_app = create_app(target_db)

    traffic_path = tmp_path / "access_logs.jsonl"
    start = datetime.now(timezone.utc) - timedelta(days=1)
    traffic_records = (
        ("POST", "/api/v3/auth/login", "anonymous"),
        ("GET", "/api/v3/search/flights", "agent"),
        ("POST", "/api/v3/holds", "agent"),
        ("POST", "/api/v3/bookings", "agent"),
        ("GET", "/api/v3/bookings/agency_a-booking-001", "agent"),
        ("POST", "/api/v3/bookings/agency_a-booking-001/pay", "agent"),
        ("POST", "/api/v3/bookings/agency_a-booking-001/cancel", "agent"),
        ("GET", "/api/v3/users/me", "agent"),
        ("PATCH", "/api/v3/users/me", "agent"),
        ("GET", "/api/v3/bookings/agency_a-booking-001/invoice", "agent"),
        ("GET", "/api/m/v2/fares", "agent"),
    )
    with traffic_path.open("w", encoding="utf-8", newline="\n") as output:
        for index, (method, path, role) in enumerate(traffic_records):
            output.write(
                json.dumps(
                    {
                        "ts": (start + timedelta(seconds=index)).isoformat(),
                        "method": method,
                        "path": path,
                        "status": 200,
                        "role": role,
                        "agency": "agency_a",
                        "ua": (
                            "SkyVoyageMobile/3.0 (Android)"
                            if path == "/api/m/v2/fares"
                            else "SkyVoyageWeb/3.0 Chrome"
                        ),
                        "bytes": 256,
                    }
                )
                + "\n"
            )

    with TestClient(target_app) as target_client:
        def in_process_target(request: httpx.Request) -> httpx.Response:
            target_response = target_client.request(
                request.method,
                str(request.url),
                headers=dict(request.headers),
                content=request.content,
            )
            return httpx.Response(
                target_response.status_code,
                headers=dict(target_response.headers),
                content=target_response.content,
                request=request,
            )

        client = httpx.Client(transport=httpx.MockTransport(in_process_target))
        gate = SafetyGate(
            vault,
            audit_log=AuditLog(tmp_path / "audit.jsonl"),
            rate_limiter=RateLimiter(100.0, 100.0),
            health_monitor=HealthMonitor(window_size=500),
            client=client,
        )
        try:
            result = run_recon_inventory(
                gate,
                vault,
                traffic_path=traffic_path,
                har_dir=tmp_path / "har",
                database_path=tmp_path / "knowledge.sqlite3",
                openapi_path=tmp_path / "openapi.json",
                account_names={"agent_a"},
            )
        finally:
            client.close()

    records = {(item.method, item.path): item for item in result.inventory}
    expected_active = {
        ("GET", "/api/v3/bookings/{id}/invoice"),
        ("POST", "/api/v3/bookings"),
        ("POST", "/api/v3/bookings/{id}/cancel"),
        ("POST", "/api/v3/holds"),
        ("PATCH", "/api/v3/users/me"),
    }
    for key in expected_active:
        assert records[key].classification == "active"

    legacy = records[("GET", "/api/v1/bookings/{id}")]
    assert legacy.classification == "zombie"
    assert legacy.auth_required is False
    assert "passport_number" in legacy.data_exposed

    debug = records[("GET", "/api/v3/debug/config")]
    assert debug.classification == "zombie"
    assert debug.auth_required is True
    assert "example_setting" in debug.data_exposed

    mobile = records[("GET", "/api/m/v2/fares")]
    assert mobile.classification == "shadow"
    assert mobile.auth_required is True
    assert mobile.last_traffic is not None
    assert mobile.owner == "Mobile platform team"

    document = json.loads(result.openapi_path.read_text(encoding="utf-8"))
    assert document["openapi"] == "3.0.3"
    assert "/api/v3/bookings/{id}/invoice" in document["paths"]
    assert document["paths"]["/api/v1/bookings/{id}"]["get"][
        "x-skywarden-classification"
    ] == "zombie"

    knowledge_base = KnowledgeBase(tmp_path / "knowledge.sqlite3")
    graph_data = EndpointGraph(knowledge_base).as_dict()
    assert len(graph_data["nodes"]) == len(result.inventory)
    assert graph_data["edges"]
    har_text = (tmp_path / "har" / "agent_a.har").read_text(encoding="utf-8")
    assert "synthetic-agent_a-password" not in har_text
    assert "Bearer " not in har_text
    assert "[REDACTED]" in har_text

    traffic = load_traffic(traffic_path)
    assert traffic[("GET", "/api/v3/search/flights")].last_traffic.tzinfo is not None
