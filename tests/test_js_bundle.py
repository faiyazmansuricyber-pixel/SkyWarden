from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.seed import seed_database
from target_app.admin import create_admin_app
from target_app.main import create_app


TEST_PASSWORDS = {
    "TEST_ADMIN_A_PASSWORD": "fake-admin-a-password",
    "TEST_AGENT_A_PASSWORD": "fake-agent-a-password",
    "TEST_SUBAGENT_A_PASSWORD": "fake-subagent-a-password",
    "TEST_ADMIN_B_PASSWORD": "fake-admin-b-password",
    "TEST_AGENT_B_PASSWORD": "fake-agent-b-password",
}


@pytest.fixture
def apps(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient]]:
    db_path = tmp_path / "skyvoyage-js-bundle.sqlite3"
    seed_database(db_path, environ=TEST_PASSWORDS)
    with (
        TestClient(create_app(db_path)) as target,
        TestClient(
            create_admin_app(db_path),
            client=("127.0.0.1", 51002),
        ) as admin,
    ):
        yield target, admin


def fetch_bundle(target: TestClient) -> tuple[str, str]:
    page = target.get("/")
    assert page.status_code == 200
    match = re.search(
        r'<script src="(/app\.([0-9a-f]{12})\.js)" defer></script>',
        page.text,
    )
    assert match is not None
    path, expected_hash = match.groups()

    response = target.get(path)
    assert response.status_code == 200
    content = response.text
    actual_hash = hashlib.sha256(response.content).hexdigest()[:12]
    assert actual_hash == expected_hash
    return path, content


def test_static_bundle_hash_tracks_routes_and_fix_s1(
    apps: tuple[TestClient, TestClient],
) -> None:
    target, admin = apps
    default_path, default_bundle = fetch_bundle(target)
    for route in (
        "/api/v3/auth/login",
        "/api/v3/search/flights",
        "/api/v3/users/me",
        "/api/v3/holds",
        "/api/v3/bookings",
        "/pay",
        "/cancel",
    ):
        assert route in default_bundle
    assert "/api/m/v2/fares" not in default_bundle
    assert "/api/v3/debug/config" not in default_bundle
    assert "/api/v3/bookings/{id}/invoice" not in default_bundle

    release_update = admin.put("/__admin/release", json={"version": "v3.1"})
    assert release_update.status_code == 200
    release_path, release_bundle = fetch_bundle(target)
    assert release_path != default_path
    assert "/api/v3/bookings/{id}/invoice" in release_bundle
    assert "/api/m/v2/fares" not in release_bundle
    assert "/api/v3/debug/config" not in release_bundle
    assert target.get(default_path).status_code == 404

    flag_update = admin.patch(
        "/__admin/flags",
        json={"flag": "FIX_S1", "enabled": True},
    )
    assert flag_update.status_code == 200
    fixed_path, fixed_bundle = fetch_bundle(target)
    assert fixed_path != release_path
    assert "/api/m/v2/fares" in fixed_bundle
    assert "/api/v3/debug/config" not in fixed_bundle
    assert target.get(release_path).status_code == 404
