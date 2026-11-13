from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from engine.recon.paths import normalize_endpoint_path
from engine.safety.gate import ALLOWED_HOST, ALLOWED_PORT, RiskClass, SafetyGate, build_request
from engine.safety.vault import Vault, VaultAccount


TARGET_ROOT = f"http://{ALLOWED_HOST}:{ALLOWED_PORT}"
BOOKING_PATH = re.compile(r"^/api/v3/bookings/([^/]+)(?:/.*)?$")
PROBE_PREFIXES = (
    "/api/v1/",
    "/api/old/",
    "/api/internal/",
    "/api/test/",
    "/api/beta/",
    "/api/debug/",
)


@dataclass(frozen=True)
class ProbeResult:
    method: str
    path: str
    status_code: int
    anonymous_status: int
    auth_required: bool
    data_exposed: tuple[str, ...]
    source: str = "probe"

    @property
    def reachable(self) -> bool:
        return self.status_code < 400 or self.status_code == 405


def build_probe_candidates(
    observed_paths: set[str] | list[str] | tuple[str, ...],
    *,
    max_candidates: int = 12,
) -> list[str]:
    candidates = ["/api/v3/debug/config", "/api/m/v2/fares"]
    for path in sorted(observed_paths):
        parsed_path = urlsplit(path).path
        match = BOOKING_PATH.fullmatch(parsed_path)
        if match is None:
            continue
        booking_route = f"bookings/{match.group(1)}"
        candidates.extend(f"{prefix}{booking_route}" for prefix in PROBE_PREFIXES)
    unique = list(dict.fromkeys(candidates))
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive.")
    return unique[:max_candidates]


def _json_field_names(response_body: bytes) -> tuple[str, ...]:
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ()
    names: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                names.add(str(key))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return tuple(sorted(names))


def _login(gate: SafetyGate, account: VaultAccount) -> str:
    response = gate.send(
        build_request(
            "POST",
            f"{TARGET_ROOT}/api/v3/auth/login",
            body_json={"username": account.username, "password": account.password},
        ),
        RiskClass.R0,
        {"account": account.username},
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Local test-account login failed with HTTP {response.status_code}.")
    token = response.json().get("access_token")
    if not isinstance(token, str):
        raise RuntimeError("Local test-account login did not return a bearer token.")
    return token


def probe_candidates(
    gate: SafetyGate,
    vault: Vault,
    paths: list[str],
    *,
    account_name: str = "agent_a",
    min_interval_seconds: float = 0.21,
) -> list[ProbeResult]:
    account = vault.account(account_name)
    if account is None:
        raise ValueError(f"Vault account {account_name!r} is unavailable.")
    token = _login(gate, account)
    last_sent = 0.0
    results: list[ProbeResult] = []

    def send(path: str, headers: dict[str, str], context: dict[str, object]):
        nonlocal last_sent
        now = time.monotonic()
        wait = min_interval_seconds - (now - last_sent)
        if last_sent and wait > 0:
            time.sleep(wait)
        last_sent = time.monotonic()
        return gate.send(
            build_request("GET", f"{TARGET_ROOT}{path}", headers=headers),
            RiskClass.R0,
            context,
        )

    authenticated_headers = {"Authorization": f"Bearer {token}"}
    for raw_path in paths:
        path = urlsplit(raw_path).path
        if not path.startswith("/api/"):
            continue
        anonymous_headers: dict[str, str] = {}
        if path == "/api/m/v2/fares":
            anonymous_headers["User-Agent"] = "SkyVoyageMobile/3.0 (Android)"
            authenticated_headers["User-Agent"] = "SkyVoyageMobile/3.0 (Android)"
        anonymous_response = send(path, anonymous_headers, {})
        auth_required = anonymous_response.status_code in {401, 403}
        response = anonymous_response
        if auth_required:
            response = send(
                path,
                authenticated_headers,
                {"account": account.username},
            )
        results.append(
            ProbeResult(
                method="GET",
                path=normalize_endpoint_path(path),
                status_code=response.status_code,
                anonymous_status=anonymous_response.status_code,
                auth_required=auth_required,
                data_exposed=_json_field_names(response.content),
            )
        )
    return results
