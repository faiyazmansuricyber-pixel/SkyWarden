from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from engine.safety.approvals import (
    CliApprovalProvider,
    TestApprovalProvider as ApprovalForTests,
)
from engine.safety.audit import AuditLog
from engine.safety.gate import Blocked, RiskClass, SafetyGate, build_request
from engine.safety.health import HealthMonitor
from engine.safety.rate_limiter import RateLimiter
from engine.safety.vault import Vault, VaultAccount


@pytest.fixture
def vault() -> Vault:
    return Vault(
        {
            "agent_a": VaultAccount(
                username="agent_a",
                password="synthetic-password",
                agency_id="agency_a",
                role="agent",
            )
        }
    )


def create_gate(
    tmp_path: Path,
    vault: Vault,
    handler,
    *,
    approval_provider=None,
    health_monitor=None,
    endpoint_rate: float = 100.0,
) -> tuple[SafetyGate, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    gate = SafetyGate(
        vault,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        rate_limiter=RateLimiter(100.0, endpoint_rate),
        health_monitor=health_monitor or HealthMonitor(),
        approval_provider=approval_provider or ApprovalForTests(),
        client=client,
    )
    return gate, client


def authenticated_request(
    vault: Vault,
    method: str = "GET",
    path: str = "/api/v3/search/flights",
) -> httpx.Request:
    vault.register_token("agent_a", "synthetic-token")
    return build_request(
        method,
        f"http://127.0.0.1:8001{path}",
        headers={"Authorization": "Bearer synthetic-token"},
    )


def test_scope_blocks_external_hosts_and_admin_paths(tmp_path: Path, vault: Vault) -> None:
    calls = []
    gate, client = create_gate(
        tmp_path,
        vault,
        lambda request: calls.append(request) or httpx.Response(200),
    )
    try:
        for request in (
            build_request("GET", "http://localhost:8001/api/v3/search/flights"),
            build_request("GET", "http://127.0.0.1:8001/__admin/state"),
        ):
            with pytest.raises(Blocked):
                gate.send(request, RiskClass.R0, {})
        assert calls == []
    finally:
        client.close()


def test_endpoint_rate_limit_blocks_the_third_request(
    tmp_path: Path, vault: Vault
) -> None:
    gate, client = create_gate(
        tmp_path,
        vault,
        lambda request: httpx.Response(200, request=request),
        endpoint_rate=2.0,
    )
    try:
        for _ in range(2):
            gate.send(authenticated_request(vault), RiskClass.R0, {})
        with pytest.raises(Blocked, match="rate limit"):
            gate.send(authenticated_request(vault), RiskClass.R0, {})
    finally:
        client.close()


def test_r2_requires_approval_and_reuses_one_plan_approval(
    tmp_path: Path, vault: Vault
) -> None:
    calls = []
    answers = []
    messages = []

    def approve_prompt(prompt: str) -> str:
        answers.append(prompt)
        return "approve"

    gate, client = create_gate(
        tmp_path,
        vault,
        lambda request: calls.append(request)
        or httpx.Response(200, request=request),
        approval_provider=CliApprovalProvider(approve_prompt, messages.append),
    )
    context = {
        "account": "agent_a",
        "resource_owner": "agency_a",
        "justification": "Verify the local mock refund behavior.",
        "plan_id": "plan-refund-test",
    }
    request_path = "/api/v3/bookings/agency_a-booking-001/cancel"
    try:
        for _ in range(2):
            gate.send(authenticated_request(vault, "POST", request_path), RiskClass.R2, context)
        assert len(calls) == 2
        assert answers == ["Approve this financial test? Type 'approve': "]
        assert messages == ["R2 approval required for plan plan-refund-test."]

        denied_gate, denied_client = create_gate(
            tmp_path,
            vault,
            lambda request: calls.append(request)
            or httpx.Response(200, request=request),
        )
        try:
            with pytest.raises(Blocked, match="human approval"):
                denied_gate.send(
                    authenticated_request(vault, "POST", request_path),
                    RiskClass.R2,
                    context,
                )
            assert len(calls) == 2
        finally:
            denied_client.close()
    finally:
        client.close()


def test_health_monitor_pauses_after_twenty_responses(tmp_path: Path, vault: Vault) -> None:
    monitor = HealthMonitor(baseline_latency_ms=100, window_size=20)
    gate, client = create_gate(
        tmp_path,
        vault,
        lambda request: httpx.Response(503, request=request),
        health_monitor=monitor,
    )
    try:
        for _ in range(20):
            gate.send(authenticated_request(vault), RiskClass.R0, {})
        assert monitor.snapshot().paused
        assert monitor.snapshot().sample_count == 20
        with pytest.raises(Blocked, match="Health monitor"):
            gate.send(authenticated_request(vault), RiskClass.R0, {})
    finally:
        client.close()


def test_health_monitor_pauses_when_p95_exceeds_three_times_baseline() -> None:
    monitor = HealthMonitor(baseline_latency_ms=100, window_size=20)
    for _ in range(20):
        snapshot = monitor.record(301, 200)
    assert snapshot.paused
    assert snapshot.p95_latency_ms == 301
    assert snapshot.reason == "p95 latency exceeded three times baseline."


def test_audit_log_never_persists_login_secrets(tmp_path: Path, vault: Vault) -> None:
    def login_response(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["password"] == "synthetic-password"
        return httpx.Response(
            200,
            json={"access_token": "private-synthetic-token"},
            headers={"Set-Cookie": "private-synthetic-cookie=secret"},
        )

    gate, client = create_gate(tmp_path, vault, login_response)
    try:
        request = build_request(
            "POST",
            "http://127.0.0.1:8001/api/v3/auth/login",
            headers={"X-API-Key": "private-synthetic-key"},
            body_json={"username": "agent_a", "password": "synthetic-password"},
        )
        gate.send(request, RiskClass.R0, {"account": "agent_a"})
        audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        for secret in (
            "synthetic-password",
            "private-synthetic-token",
            "private-synthetic-key",
            "private-synthetic-cookie",
        ):
            assert secret not in audit_text
        assert "[REDACTED]" in audit_text
        assert vault.is_trusted_token("private-synthetic-token")
    finally:
        client.close()
