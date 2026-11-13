from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.seed import seed_database
from target_app.db import connect_db
from target_app.main import create_app


TEST_PASSWORDS = {
    "TEST_ADMIN_A_PASSWORD": "fake-admin-a-password",
    "TEST_AGENT_A_PASSWORD": "fake-agent-a-password",
    "TEST_SUBAGENT_A_PASSWORD": "fake-subagent-a-password",
    "TEST_ADMIN_B_PASSWORD": "fake-admin-b-password",
    "TEST_AGENT_B_PASSWORD": "fake-agent-b-password",
}


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "skyvoyage-test.sqlite3"
    seed_database(db_path, environ=TEST_PASSWORDS)
    return TestClient(create_app(db_path))


def login(api: TestClient, username: str, password: str) -> str:
    response = api.post(
        "/api/v3/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def booking_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def enable_fix(api: TestClient, flag: str) -> None:
    with connect_db(api.app.state.db_path) as connection:
        row = connection.execute(
            "SELECT flags_json FROM release_flags WHERE id = 1"
        ).fetchone()
        flags = json.loads(row["flags_json"])
        flags[flag] = True
        connection.execute(
            "UPDATE release_flags SET flags_json = ? WHERE id = 1",
            (json.dumps(flags, sort_keys=True),),
        )


def test_login_returns_bearer_token_and_protected_routes_require_it(api: TestClient) -> None:
    token = login(api, "admin_a", TEST_PASSWORDS["TEST_ADMIN_A_PASSWORD"])
    assert token
    assert api.get("/api/v3/search/flights").status_code == 401
    response = api.get("/api/v3/search/flights", headers=booking_headers(token))
    assert response.status_code == 200
    assert response.json()["flights"]


def test_seeded_passwords_are_stored_as_salted_hashes(api: TestClient) -> None:
    with connect_db(api.app.state.db_path) as connection:
        user = connection.execute(
            "SELECT password_salt, password_hash FROM users WHERE username = 'admin_a'"
        ).fetchone()
    assert user is not None
    assert user["password_salt"]
    assert len(user["password_hash"]) == 32
    assert user["password_hash"] != TEST_PASSWORDS["TEST_ADMIN_A_PASSWORD"].encode()


def test_agency_a_cannot_read_agency_b_booking(api: TestClient) -> None:
    token = login(api, "admin_a", TEST_PASSWORDS["TEST_ADMIN_A_PASSWORD"])
    response = api.get(
        "/api/v3/bookings/agency_b-booking-001",
        headers=booking_headers(token),
    )
    assert response.status_code == 404


def test_booking_price_is_calculated_from_flight_data(api: TestClient) -> None:
    token = login(api, "agent_a", TEST_PASSWORDS["TEST_AGENT_A_PASSWORD"])
    headers = booking_headers(token)
    payload = {
        "flight_id": "SV100",
        "quantity": 2,
        "traveler_name": "Synthetic Traveller New",
        "passport_number": "X9000001",
    }
    response = api.post("/api/v3/bookings", headers=headers, json=payload)
    assert response.status_code == 201
    booking = response.json()
    assert booking["unit_price_cents"] == 52000
    assert booking["total_price_cents"] == 104000

    forged_price = {**payload, "total_price_cents": 1}
    rejected = api.post("/api/v3/bookings", headers=headers, json=forged_price)
    assert rejected.status_code == 422


def test_booking_can_be_cancelled_only_once(api: TestClient) -> None:
    enable_fix(api, "FIX_B3")
    token = login(api, "agent_a", TEST_PASSWORDS["TEST_AGENT_A_PASSWORD"])
    headers = booking_headers(token)
    paid = api.post("/api/v3/bookings/agency_a-booking-002/pay", headers=headers)
    first = api.post(
        "/api/v3/bookings/agency_a-booking-002/cancel", headers=headers
    )
    second = api.post(
        "/api/v3/bookings/agency_a-booking-002/cancel", headers=headers
    )
    assert paid.status_code == 200
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert first.json()["refund_amount_cents"] == first.json()["total_price_cents"]
    assert second.status_code == 409


def test_subagent_is_scoped_to_own_bookings_and_cannot_pay(api: TestClient) -> None:
    token = login(api, "subagent_a", TEST_PASSWORDS["TEST_SUBAGENT_A_PASSWORD"])
    headers = booking_headers(token)
    own = api.get("/api/v3/bookings/agency_a-booking-003", headers=headers)
    other = api.get("/api/v3/bookings/agency_a-booking-001", headers=headers)
    pay = api.post("/api/v3/bookings/agency_a-booking-003/pay", headers=headers)
    assert own.status_code == 200
    assert other.status_code == 404
    assert pay.status_code == 403
    created = api.post(
        "/api/v3/bookings",
        headers=headers,
        json={
            "flight_id": "SV100",
            "quantity": 1,
            "traveler_name": "Synthetic Traveller Subagent",
            "passport_number": "X9000002",
        },
    )
    assert created.status_code == 201


def test_profile_update_cannot_change_role(api: TestClient) -> None:
    enable_fix(api, "FIX_B5")
    token = login(api, "agent_a", TEST_PASSWORDS["TEST_AGENT_A_PASSWORD"])
    response = api.patch(
        "/api/v3/users/me",
        headers=booking_headers(token),
        json={"display_name": "Updated Agent", "role": "admin"},
    )
    assert response.status_code == 422


def test_release_flags_are_reloaded_for_each_request(api: TestClient) -> None:
    with connect_db(api.app.state.db_path) as connection:
        connection.execute(
            "UPDATE release_flags SET release_version = 'v3.0.1', flags_json = '{\"demo_flag\": true}' WHERE id = 1"
        )

    response = api.get("/")
    assert response.status_code == 200
    assert response.headers["X-SkyVoyage-Release"] == "v3.0.1"
