from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from enum import Enum
from time import perf_counter
from typing import Any, NoReturn
from urllib.parse import unquote

import httpx
from dotenv import dotenv_values

from engine.safety.approvals import ApprovalProvider, CliApprovalProvider
from engine.safety.audit import AuditLog, redact_headers
from engine.safety.health import HealthMonitor
from engine.safety.rate_limiter import RateLimitExceeded, RateLimiter
from engine.safety.vault import ROOT_DIR, Vault, VaultAccount


ALLOWED_HOST = "127.0.0.1"
ALLOWED_PORT = 8001
LOGIN_PATH = "/api/v3/auth/login"
ALLOWED_API_PREFIXES = (
    "/api/v3/",
    "/api/v1/",
    "/api/m/v2/",
    "/api/old/",
    "/api/internal/",
    "/api/test/",
    "/api/beta/",
    "/api/debug/",
)
HASHED_BUNDLE_PATTERN = re.compile(r"/app\.[0-9a-f]{12}\.js\Z")


class RiskClass(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"


class Blocked(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def build_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body_json: Any | None = None,
    content: bytes | str | None = None,
) -> httpx.Request:
    if body_json is not None and content is not None:
        raise ValueError("Provide either body_json or content, not both.")
    if body_json is not None:
        return httpx.Request(method, url, headers=headers, json=body_json)
    return httpx.Request(method, url, headers=headers, content=content)


class SafetyGate:
    def __init__(
        self,
        vault: Vault,
        *,
        audit_log: AuditLog | None = None,
        rate_limiter: RateLimiter | None = None,
        health_monitor: HealthMonitor | None = None,
        approval_provider: ApprovalProvider | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.vault = vault
        self.audit_log = audit_log or AuditLog()
        configured_values: dict[str, str] = {}
        for path in (ROOT_DIR / ".env.example", ROOT_DIR / ".env"):
            configured_values.update(
                {
                    key: value
                    for key, value in dotenv_values(path).items()
                    if value is not None
                }
            )
        configured_values.update(os.environ)
        self.rate_limiter = rate_limiter or RateLimiter(
            global_rate_per_second=float(configured_values.get("RATE_LIMIT_GLOBAL_RPS", "5")),
            endpoint_rate_per_second=float(
                configured_values.get("RATE_LIMIT_PER_ENDPOINT_RPS", "2")
            ),
        )
        self.health_monitor = health_monitor or HealthMonitor()
        self.approval_provider = approval_provider or CliApprovalProvider()
        self._client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._paused_reason: str | None = None

    @staticmethod
    def _allowed_path(path: str) -> bool:
        decoded_path = unquote(path)
        if "%" in path:
            return False
        if "\\" in decoded_path or any(segment == ".." for segment in decoded_path.split("/")):
            return False
        if decoded_path == "/__admin" or decoded_path.startswith("/__admin/"):
            return False
        return (
            decoded_path in {"/", "/favicon.ico"}
            or HASHED_BUNDLE_PATTERN.fullmatch(decoded_path) is not None
            or any(decoded_path.startswith(prefix) for prefix in ALLOWED_API_PREFIXES)
        )

    def _blocked(
        self,
        request: httpx.Request,
        risk: RiskClass | str,
        context: Mapping[str, object],
        reason: str,
    ) -> NoReturn:
        self._audit(
            request,
            risk,
            context,
            decision="blocked",
            reason=reason,
        )
        raise Blocked(reason)

    def _check_scope(
        self,
        request: httpx.Request,
        risk: RiskClass | str,
        context: Mapping[str, object],
    ) -> None:
        url = request.url
        if (
            url.scheme != "http"
            or url.host != ALLOWED_HOST
            or url.port != ALLOWED_PORT
            or bool(url.username)
            or bool(url.password)
            or not self._allowed_path(url.path)
        ):
            self._blocked(request, risk, context, "Request is outside the SkyVoyage allowlist.")

    def _check_credentials(
        self,
        request: httpx.Request,
        context: Mapping[str, object],
    ) -> VaultAccount | None:
        context_account = context.get("account")
        if context_account is not None and (
            not isinstance(context_account, str)
            or self.vault.account(context_account) is None
        ):
            self._blocked(request, "", context, "Account is not present in the vault.")

        authorization = request.headers.get("authorization")
        if request.url.path == LOGIN_PATH and authorization:
            self._blocked(request, "", context, "Login must not use a bearer token.")
        if authorization:
            scheme, separator, token = authorization.partition(" ")
            account = (
                self.vault.account_for_token(token.strip())
                if separator and scheme.lower() == "bearer"
                else None
            )
            if account is None:
                self._blocked(request, "", context, "Bearer token is not present in the vault.")
            if context_account is not None and account.username != context_account:
                self._blocked(request, "", context, "Token does not match the vault account.")
            return account

        if request.url.path == LOGIN_PATH:
            try:
                payload = json.loads(request.content)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._blocked(request, "", context, "Login payload is not valid JSON.")
            if not isinstance(payload, dict) or not self.vault.validate_login(
                payload.get("username"), payload.get("password")
            ):
                self._blocked(request, "", context, "Login credentials are not present in the vault.")
            account = self.vault.account(payload["username"])
            if context_account is not None and account is not None and account.username != context_account:
                self._blocked(request, "", context, "Login does not match the vault account.")
            return account
        return None

    def _check_risk(
        self,
        request: httpx.Request,
        risk: RiskClass | str,
        context: Mapping[str, object],
        account: VaultAccount | None,
    ) -> RiskClass:
        try:
            risk_class = RiskClass(risk)
        except ValueError:
            self._blocked(request, risk, context, "Risk class must be R0, R1, or R2.")

        method = request.method.upper()
        if risk_class is RiskClass.R0:
            if method not in {"GET", "HEAD", "OPTIONS"} and not (
                method == "POST" and request.url.path == LOGIN_PATH
            ):
                self._blocked(request, risk_class, context, "R0 requests must be read-only.")
            return risk_class

        justification = context.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            self._blocked(request, risk_class, context, "State-changing requests need justification.")
        if method in {"GET", "HEAD", "OPTIONS"}:
            self._blocked(
                request,
                risk_class,
                context,
                "R1 and R2 requests must use a state-changing HTTP method.",
            )
        if account is None:
            self._blocked(request, risk_class, context, "State-changing requests need a vault account.")
        resource_owner = context.get("resource_owner")
        if not isinstance(resource_owner, str) or resource_owner not in {
            account.username,
            account.agency_id,
        }:
            self._blocked(
                request,
                risk_class,
                context,
                "State-changing requests must target the vault account's own resources.",
            )
        if risk_class is RiskClass.R2:
            plan_id = context.get("plan_id")
            if not isinstance(plan_id, str) or not plan_id:
                self._blocked(request, risk_class, context, "R2 requests need a plan_id.")
            if not self.approval_provider.approve(context):
                self._blocked(request, risk_class, context, "R2 request lacks human approval.")
        return risk_class

    def _audit(
        self,
        request: httpx.Request,
        risk: RiskClass | str,
        context: Mapping[str, object],
        *,
        decision: str,
        reason: str,
        status_code: int | None = None,
        duration_ms: float | None = None,
        response_headers: Mapping[str, str] | None = None,
    ) -> None:
        account = context.get("account")
        plan_id = context.get("plan_id")
        self.audit_log.append(
            {
                "method": request.method.upper(),
                "path": request.url.path,
                "risk": risk.value if isinstance(risk, RiskClass) else str(risk),
                "decision": decision,
                "reason": reason,
                "account": account if isinstance(account, str) else None,
                "plan_id": plan_id if isinstance(plan_id, str) else None,
                "justification_present": bool(context.get("justification")),
                "headers": redact_headers(dict(request.headers)),
                "response_headers": redact_headers(response_headers or {}),
                "status_code": status_code,
                "duration_ms": duration_ms,
            }
        )

    def send(
        self,
        request: httpx.Request,
        risk: RiskClass | str,
        context: Mapping[str, object],
    ) -> httpx.Response:
        self._check_scope(request, risk, context)
        account = self._check_credentials(request, context)

        endpoint_key = re.sub(
            r"(?<=/bookings/)[^/]+",
            "{id}",
            request.url.path,
        )
        try:
            self.rate_limiter.check(f"{request.method.upper()}:{endpoint_key}")
        except RateLimitExceeded as error:
            self._blocked(request, risk, context, str(error))

        risk_class = self._check_risk(request, risk, context, account)
        if self.health_monitor.paused:
            self._blocked(request, risk_class, context, "Health monitor paused target requests.")
        if self._paused_reason is not None:
            self._blocked(request, risk_class, context, self._paused_reason)

        start = perf_counter()
        try:
            response = self._client.send(request)
        except httpx.RequestError as error:
            duration_ms = (perf_counter() - start) * 1000
            self._audit(
                request,
                risk_class,
                context,
                decision="failed",
                reason="Target transport failed.",
                duration_ms=duration_ms,
            )
            raise Blocked("Target transport failed.") from error

        duration_ms = (perf_counter() - start) * 1000
        self.health_monitor.record(duration_ms, response.status_code)
        self._audit(
            request,
            risk_class,
            context,
            decision="allowed",
            reason="Request passed the safety gate.",
            status_code=response.status_code,
            duration_ms=duration_ms,
            response_headers=dict(response.headers),
        )
        if request.url.path == LOGIN_PATH and 200 <= response.status_code < 300:
            try:
                token = response.json().get("access_token")
            except (ValueError, AttributeError):
                token = None
            if isinstance(token, str):
                if account is not None:
                    self.vault.register_token(account.username, token)
        return response

    def pause(self, reason: str = "Kill switch engaged.") -> None:
        if not reason.strip():
            raise ValueError("Pause reason must be non-empty.")
        self._paused_reason = reason

    def resume(self) -> None:
        self._paused_reason = None
        self.health_monitor.resume()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


_default_gate = SafetyGate(Vault.from_env())


def send(
    request: httpx.Request,
    risk: RiskClass | str,
    context: Mapping[str, object],
) -> httpx.Response:
    return _default_gate.send(request, risk, context)


def pause(reason: str = "Kill switch engaged.") -> None:
    _default_gate.pause(reason)


def resume() -> None:
    _default_gate.resume()


def set_default_gate(instance: SafetyGate) -> None:
    global _default_gate
    _default_gate = instance
