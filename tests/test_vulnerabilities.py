from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.reset import reset_database
from scripts.seed import seed_database
from target_app.admin import create_admin_app
from target_app.db import DEFAULT_FIX_FLAGS
from target_app.main import create_app


TEST_PASSWORDS = {
    "TEST_ADMIN_A_PASSWORD": "fake-admin-a-password",
    "TEST_AGENT_A_PASSWORD": "fake-agent-a-password",
    "TEST_SUBAGENT_A_PASSWORD": "fake-subagent-a-password",
    "TEST_ADMIN_B_PASSWORD": "fake-admin-b-password",
    "TEST_AGENT_B_PASSWORD": "fake-agent-b-password",
}


@pytest.fixture
def apps(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient, Path]]:
    db_path = tmp_path / "skyvoyage-vulnerability-tests.sqlite3"
    seed_database(db_path, environ=TEST_PASSWORDS)
    with (
        TestClient(create_app(db_path)) as target,
        TestClient(
            create_admin_app(db_path),
            client=("127.0.0.1", 51002),
        ) as admin,
    ):
        yield target, admin, db_path


def login(target: TestClient, username: str = "agent_a") -> str:
    response = target.post(
        "/api/v3/auth/login",
        json={"username": username, "password": TEST_PASSWORDS[f"TEST_{username.upper()}_PASSWORD"]},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def set_flag(admin: TestClient, flag: str, enabled: bool = True) -> None:
    response = admin.patch(
        "/__admin/flags",
        json={"flag": flag, "enabled": enabled},
    )
    assert response.status_code == 200


def test_b1_invoice_is_release_gated_and_fix_enforces_ownership(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target))
    invoice = "/api/v3/bookings/agency_b-booking-001/invoice"
    assert target.get(invoice, headers=headers).status_code == 404

    assert admin.put("/__admin/release", json={"version": "v3.1"}).status_code == 200
    vulnerable = target.get(invoice, headers=headers)
    assert vulnerable.status_code == 200
    assert vulnerable.json()["agency_id"] == "agency_b"

    set_flag(admin, "FIX_B1")
    assert target.get(invoice, headers=headers).status_code == 404
    own = target.get(
        "/api/v3/bookings/agency_a-booking-001/invoice",
        headers=headers,
    )
    assert own.status_code == 200
    assert own.json()["agency_id"] == "agency_a"


def test_b2_client_price_is_trusted_only_when_fix_is_off(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target))
    payload = {
        "flight_id": "SV100",
        "quantity": 2,
        "traveler_name": "Synthetic Traveller B2",
        "passport_number": "X8000001",
        "total_price": "1.25",
    }
    vulnerable = target.post("/api/v3/bookings", headers=headers, json=payload)
    assert vulnerable.status_code == 201
    assert vulnerable.json()["total_price_cents"] == 125

    set_flag(admin, "FIX_B2")
    payload["passport_number"] = "X8000002"
    fixed = target.post("/api/v3/bookings", headers=headers, json=payload)
    assert fixed.status_code == 201
    assert fixed.json()["total_price_cents"] == 104000


def test_b3_double_refund_is_blocked_by_fix(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target))

    def create_paid_booking(passport_number: str) -> str:
        booking = target.post(
            "/api/v3/bookings",
            headers=headers,
            json={
                "flight_id": "SV100",
                "quantity": 1,
                "traveler_name": "Synthetic Traveller B3",
                "passport_number": passport_number,
            },
        )
        assert booking.status_code == 201
        booking_id = booking.json()["id"]
        assert target.post(f"/api/v3/bookings/{booking_id}/pay", headers=headers).status_code == 200
        return booking_id

    vulnerable_id = create_paid_booking("X8000003")
    vulnerable_path = f"/api/v3/bookings/{vulnerable_id}/cancel"
    first = target.post(vulnerable_path, headers=headers)
    second = target.post(vulnerable_path, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["refund_amount_cents"] > 0
    assert second.json()["refund_amount_cents"] == 2 * first.json()["refund_amount_cents"]

    set_flag(admin, "FIX_B3")
    fixed_id = create_paid_booking("X8000004")
    fixed_path = f"/api/v3/bookings/{fixed_id}/cancel"
    fixed_first = target.post(fixed_path, headers=headers)
    fixed_second = target.post(fixed_path, headers=headers)
    assert fixed_first.status_code == 200
    assert fixed_second.status_code == 409
    unchanged = target.get(
        f"/api/v3/bookings/{fixed_id}",
        headers=headers,
    )
    assert unchanged.json()["refund_amount_cents"] == fixed_first.json()["refund_amount_cents"]


def test_b4_negative_hold_reduces_price_only_when_fix_is_off(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target))
    payload = {"flight_id": "SV100", "quantity": -2}
    vulnerable = target.post("/api/v3/holds", headers=headers, json=payload)
    assert vulnerable.status_code == 201
    assert vulnerable.json()["total_price_cents"] == -104000

    set_flag(admin, "FIX_B4")
    assert target.post("/api/v3/holds", headers=headers, json=payload).status_code == 422


def test_b5_role_mass_assignment_is_blocked_by_fix(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target, username="subagent_a"))
    payload = {"role": "admin"}

    set_flag(admin, "FIX_B5")
    blocked = target.patch("/api/v3/users/me", headers=headers, json=payload)
    assert blocked.status_code == 422
    assert target.get("/api/v3/users/me", headers=headers).json()["user"]["role"] == "subagent"

    set_flag(admin, "FIX_B5", enabled=False)
    vulnerable = target.patch("/api/v3/users/me", headers=headers, json=payload)
    assert vulnerable.status_code == 200
    assert vulnerable.json()["user"]["role"] == "admin"


def test_z1_unauthenticated_passport_route_returns_404_with_fix(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    path = "/api/v1/bookings/agency_b-booking-001"
    vulnerable = target.get(path)
    assert vulnerable.status_code == 200
    assert vulnerable.json()["passport_number"] == "X0000031"

    set_flag(admin, "FIX_Z1")
    assert target.get(path).status_code == 404


def test_z2_debug_config_returns_only_fake_values_and_fix_hides_route(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target))
    vulnerable = target.get("/api/v3/debug/config", headers=headers)
    assert vulnerable.status_code == 200
    assert vulnerable.json()["example_setting"] == "FAKE_ONLY_NOT_A_SECRET"

    set_flag(admin, "FIX_Z2")
    assert target.get("/api/v3/debug/config", headers=headers).status_code == 404


def test_s1_mobile_fares_and_fix_reference_are_flagged_dynamically(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    target, admin, _ = apps
    headers = auth(login(target))
    bundle_off = target.get("/app.js")
    assert "/api/m/v2/fares" not in bundle_off.text

    mobile = target.get(
        "/api/m/v2/fares",
        headers={**headers, "User-Agent": "SkyVoyageMobile/1.0 (Android)"},
    )
    assert mobile.status_code == 200
    assert mobile.json()["fares"]
    desktop = target.get(
        "/api/m/v2/fares",
        headers={**headers, "User-Agent": "SkyVoyageWeb/1.0"},
    )
    assert desktop.status_code == 404

    set_flag(admin, "FIX_S1")
    bundle_on = target.get("/app.js")
    assert bundle_on.status_code == 200
    assert "/api/m/v2/fares" in bundle_on.text
    assert target.get(
        "/api/m/v2/fares",
        headers={**headers, "User-Agent": "SkyVoyageMobile/1.0 (Android)"},
    ).status_code == 200


def test_admin_control_app_rejects_non_loopback_clients(
    tmp_path: Path,
) -> None:
    admin = TestClient(
        create_admin_app(tmp_path / "admin-loopback.sqlite3"),
        client=("192.0.2.10", 51002),
    )
    assert admin.get("/__admin/state").status_code == 403


def test_reset_restores_v30_and_all_fix_flags_off(
    apps: tuple[TestClient, TestClient, Path],
) -> None:
    _, admin, db_path = apps
    assert admin.put("/__admin/release", json={"version": "v3.1"}).status_code == 200
    for flag in DEFAULT_FIX_FLAGS:
        set_flag(admin, flag)

    reset_database(db_path, environ=TEST_PASSWORDS)
    state = admin.get("/__admin/state")
    assert state.status_code == 200
    assert state.json()["release_version"] == "v3.0"
    assert state.json()["flags"] == DEFAULT_FIX_FLAGS
