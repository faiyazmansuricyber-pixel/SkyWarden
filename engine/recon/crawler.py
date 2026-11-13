from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Page, Route, sync_playwright

from engine.recon.js_routes import extract_routes
from engine.recon.paths import normalize_endpoint_path
from engine.safety.audit import redact_headers
from engine.safety.gate import ALLOWED_HOST, ALLOWED_PORT, Blocked, RiskClass, SafetyGate, build_request
from engine.safety.vault import Vault, VaultAccount


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_HAR_DIR = ROOT_DIR / "data" / "recon"
TARGET_ROOT = f"http://{ALLOWED_HOST}:{ALLOWED_PORT}"
SAFE_RESPONSE_HEADERS = {
    "allow",
    "cache-control",
    "content-type",
    "www-authenticate",
    "x-skyvoyage-release",
}


@dataclass
class CrawlResult:
    username: str
    role: str
    discovered_paths: set[str] = field(default_factory=set)
    requests: list[dict[str, object]] = field(default_factory=list)
    har_path: Path | None = None


def _safe_har_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _har_header_list(headers: dict[str, str]) -> list[dict[str, str]]:
    safe_headers = redact_headers(headers)
    return [
        {"name": name, "value": value}
        for name, value in sorted(safe_headers.items())
    ]


def _har_entry(
    request: object,
    response_status: int,
    response_headers: dict[str, str],
    response_size: int,
    started_at: datetime,
    elapsed_ms: float,
) -> dict[str, object]:
    request_headers = dict(getattr(request, "headers"))
    request_url = str(getattr(request, "url"))
    method = str(getattr(request, "method"))
    response_type = response_headers.get("content-type", "application/octet-stream")
    return {
        "startedDateTime": started_at.isoformat(),
        "time": elapsed_ms,
        "request": {
            "method": method,
            "url": _safe_har_url(request_url),
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": _har_header_list(request_headers),
            "queryString": [],
            "headersSize": -1,
            "bodySize": -1,
        },
        "response": {
            "status": response_status,
            "statusText": "",
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": _har_header_list(response_headers),
            "content": {
                "size": response_size,
                "mimeType": response_type.split(";", 1)[0],
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": response_size,
        },
        "cache": {},
        "timings": {"send": -1, "wait": elapsed_ms, "receive": 0},
    }


def _write_har(path: Path, entries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "log": {
            "version": "1.2",
            "creator": {"name": "SkyWarden", "version": "M3"},
            "entries": entries,
        }
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")


def _safe_filename(username: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", username)


def _wait_for_portable_rate_limit(last_sent: list[float], interval: float) -> None:
    now = time.monotonic()
    wait = interval - (now - last_sent[0])
    if last_sent[0] and wait > 0:
        time.sleep(wait)
    last_sent[0] = time.monotonic()


def _crawl_account(
    context: BrowserContext,
    gate: SafetyGate,
    account: VaultAccount,
    har_dir: Path,
    min_interval_seconds: float,
    last_sent: list[float],
) -> CrawlResult:
    result = CrawlResult(username=account.username, role=account.role)
    page: Page = context.new_page()
    har_entries: list[dict[str, object]] = []
    bundle_sources: list[str] = []

    def relay(route: Route) -> None:
        browser_request = route.request
        _wait_for_portable_rate_limit(last_sent, min_interval_seconds)
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        request = build_request(
            browser_request.method,
            browser_request.url,
            headers=dict(browser_request.headers),
            content=browser_request.post_data_buffer,
        )
        try:
            response = gate.send(
                request,
                RiskClass.R0,
                {"account": account.username},
            )
        except Blocked:
            route.abort()
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        response_headers = dict(response.headers)
        if browser_request.url.endswith(".js") and "javascript" in response_headers.get(
            "content-type", ""
        ):
            bundle_sources.append(response.text)
        if browser_request.url.split("?", 1)[0].startswith(f"{TARGET_ROOT}/api/"):
            result.discovered_paths.add(
                normalize_endpoint_path(urlsplit(browser_request.url).path)
            )
            result.requests.append(
                {
                    "method": browser_request.method.upper(),
                    "path": normalize_endpoint_path(urlsplit(browser_request.url).path),
                    "status_code": response.status_code,
                    "role": account.role,
                }
            )
        har_entries.append(
            _har_entry(
                browser_request,
                response.status_code,
                response_headers,
                len(response.content),
                started_at,
                elapsed_ms,
            )
        )
        fulfilled_headers = {
            key: value
            for key, value in response_headers.items()
            if key.lower() in SAFE_RESPONSE_HEADERS
        }
        route.fulfill(
            status=response.status_code,
            headers=fulfilled_headers,
            body=response.content,
        )

    page.route("**/*", relay)
    page.goto(f"{TARGET_ROOT}/", wait_until="networkidle")
    page.locator("#username").fill(account.username)
    page.locator("#password").fill(account.password)
    page.locator("#login").click()
    page.wait_for_function(
        "document.querySelector('#output').textContent.includes('Signed in.')",
        timeout=5000,
    )
    page.locator("#profile").click()
    page.wait_for_function(
        f"document.querySelector('#output').textContent.includes('{account.username}')",
        timeout=5000,
    )
    page.locator("#search").click()
    page.wait_for_function(
        "document.querySelector('#output').textContent.includes('flights')",
        timeout=5000,
    )

    for source in bundle_sources:
        result.discovered_paths.update(extract_routes(source))
    result.har_path = har_dir / f"{_safe_filename(account.username)}.har"
    _write_har(result.har_path, har_entries)
    page.close()
    return result


def crawl_roles(
    gate: SafetyGate,
    vault: Vault,
    *,
    account_names: set[str] | None = None,
    har_dir: Path = DEFAULT_HAR_DIR,
    min_interval_seconds: float = 0.21,
) -> list[CrawlResult]:
    accounts = [
        account
        for account in vault.accounts()
        if account_names is None or account.username in account_names
    ]
    if not accounts:
        raise ValueError("No matching vault accounts are available for the crawl.")

    results: list[CrawlResult] = []
    last_sent = [0.0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for account in accounts:
                context = browser.new_context(service_workers="block")
                try:
                    results.append(
                        _crawl_account(
                            context,
                            gate,
                            account,
                            har_dir,
                            min_interval_seconds,
                            last_sent,
                        )
                    )
                finally:
                    context.close()
        finally:
            browser.close()
    return results
