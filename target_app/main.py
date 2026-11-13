from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from target_app.db import (
    DEFAULT_DB_PATH,
    PASSWORD_HASH_ITERATIONS,
    connect_db,
    initialize_database,
    read_release_flags,
)


TOKEN_LIFETIME_SECONDS = 12 * 60 * 60
HOLD_LIFETIME_SECONDS = 15 * 60
STATIC_DIR = Path(__file__).resolve().parent / "static"

bearer_scheme = HTTPBearer(auto_error=False)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class HoldRequest(StrictModel):
    flight_id: str = Field(min_length=1, max_length=32)
    quantity: int = Field(ge=-9, le=9)


class BookingRequest(HoldRequest):
    traveler_name: str = Field(
        pattern=r"^(Synthetic|Demo) Traveller(?: [A-Za-z0-9-]+){0,3}$",
        max_length=100,
    )
    passport_number: str = Field(pattern=r"^X\d{7}$")
    hold_id: str | None = Field(default=None, min_length=1, max_length=36)
    total_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class ProfileUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    role: Literal["admin", "agent", "subagent"] | None = None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _account_payload(user: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "agency_id": user["agency_id"],
        "role": user["role"],
        "display_name": user["display_name"],
        "email": user["email"],
        "phone": user["phone"],
    }


def _booking_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "agency_id": row["agency_id"],
        "flight_id": row["flight_id"],
        "traveler_name": row["traveler_name"],
        "passport_number": row["passport_number"],
        "quantity": row["quantity"],
        "unit_price_cents": row["unit_price_cents"],
        "total_price_cents": row["total_price_cents"],
        "currency": row["currency"],
        "status": row["status"],
        "refund_amount_cents": row["refund_amount_cents"],
        "created_at": row["created_at"],
    }


def _visible_booking_query() -> str:
    return """
        SELECT b.*, f.currency
        FROM bookings AS b
        JOIN flights AS f ON f.id = b.flight_id
        WHERE b.id = ?
          AND b.agency_id = ?
          AND (? != 'subagent' OR b.created_by_user_id = ?)
    """


def _get_visible_booking(
    connection: sqlite3.Connection, booking_id: str, user: sqlite3.Row
) -> sqlite3.Row | None:
    return connection.execute(
        _visible_booking_query(),
        (booking_id, user["agency_id"], user["role"], user["id"]),
    ).fetchone()


def _require_roles(user: sqlite3.Row, *roles: str) -> None:
    if user["role"] not in roles:
        raise HTTPException(status_code=403, detail="This role cannot perform that action.")


def _ensure_capacity(
    connection: sqlite3.Connection,
    flight: sqlite3.Row,
    quantity: int,
    exclude_hold_id: str | None = None,
) -> None:
    booked = connection.execute(
        """
        SELECT COALESCE(SUM(quantity), 0)
        FROM bookings
        WHERE flight_id = ? AND status != 'cancelled'
        """,
        (flight["id"],),
    ).fetchone()[0]
    hold_query = """
        SELECT COALESCE(SUM(quantity), 0)
        FROM holds
        WHERE flight_id = ? AND status = 'active' AND expires_at > ?
    """
    now = int(time.time())
    if exclude_hold_id is None:
        held = connection.execute(hold_query, (flight["id"], now)).fetchone()[0]
    else:
        held = connection.execute(
            hold_query + " AND id != ?", (flight["id"], now, exclude_hold_id)
        ).fetchone()[0]

    if booked + held + quantity > flight["capacity"]:
        raise HTTPException(status_code=409, detail="Not enough seats are available.")


def _validate_profile_update(update: ProfileUpdate) -> dict[str, str | None]:
    values = update.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=422, detail="At least one profile field is required.")

    if "display_name" in values:
        values["display_name"] = values["display_name"].strip()
        if not values["display_name"]:
            raise HTTPException(status_code=422, detail="Name cannot be empty.")

    if "email" in values and values["email"] is not None:
        email = values["email"].strip()
        if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}", email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        values["email"] = email

    if "phone" in values and values["phone"] is not None:
        phone = values["phone"].strip()
        if not re.fullmatch(r"[0-9+(). -]{1,32}", phone):
            raise HTTPException(status_code=422, detail="Enter a valid phone number.")
        values["phone"] = phone

    return values


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    initialize_database(db_path)
    app = FastAPI(
        title="SkyVoyage",
        version="3.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.db_path = db_path

    @app.middleware("http")
    async def load_runtime_configuration(request: Request, call_next: Any) -> Response:
        release_version, flags = read_release_flags(app.state.db_path)
        request.state.release_version = release_version
        request.state.flags = flags
        response = await call_next(request)
        response.headers["X-SkyVoyage-Release"] = release_version
        return response

    def authenticated_user(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
        ],
    ) -> sqlite3.Row:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Bearer authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        with connect_db(app.state.db_path) as connection:
            user = connection.execute(
                """
                SELECT u.*
                FROM tokens AS t
                JOIN users AS u ON u.id = t.user_id
                WHERE t.token_hash = ? AND t.expires_at > ?
                """,
                (_token_digest(credentials.credentials), int(time.time())),
            ).fetchone()

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    user_dependency = Depends(authenticated_user)

    @app.get("/", include_in_schema=False)
    def portal() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/app.js", include_in_schema=False)
    def portal_script() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

    @app.post("/api/v3/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, str]:
        with connect_db(app.state.db_path) as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE username = ?", (payload.username,)
            ).fetchone()

        if user is None:
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            payload.password.encode("utf-8"),
            user["password_salt"],
            PASSWORD_HASH_ITERATIONS,
        )
        if not hmac.compare_digest(candidate, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with connect_db(app.state.db_path) as connection:
            connection.execute(
                "INSERT INTO tokens (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (_token_digest(token), user["id"], now + TOKEN_LIFETIME_SECONDS, now),
            )

        response.headers["Cache-Control"] = "no-store"
        return {"access_token": token, "token_type": "bearer"}

    @app.get("/api/v3/search/flights")
    def search_flights(
        origin: str | None = Query(default=None, max_length=3),
        destination: str | None = Query(default=None, max_length=3),
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        del user
        query = "SELECT * FROM flights WHERE 1 = 1"
        parameters: list[str] = []
        if origin:
            query += " AND origin = ?"
            parameters.append(origin.strip().upper())
        if destination:
            query += " AND destination = ?"
            parameters.append(destination.strip().upper())
        query += " ORDER BY depart_at"

        with connect_db(app.state.db_path) as connection:
            flights = connection.execute(query, parameters).fetchall()
        return {
            "flights": [
                {
                    "id": flight["id"],
                    "origin": flight["origin"],
                    "destination": flight["destination"],
                    "depart_at": flight["depart_at"],
                    "base_fare_cents": flight["base_fare_cents"],
                    "currency": flight["currency"],
                    "capacity": flight["capacity"],
                }
                for flight in flights
            ]
        }

    @app.post("/api/v3/holds", status_code=201)
    def create_hold(
        payload: HoldRequest,
        request: Request,
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        if payload.quantity == 0 or (
            payload.quantity < 0 and request.state.flags["FIX_B4"]
        ):
            raise HTTPException(status_code=422, detail="Quantity must be between 1 and 9.")
        now = int(time.time())
        hold_id = str(uuid4())
        with connect_db(app.state.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            flight = connection.execute(
                "SELECT * FROM flights WHERE id = ?", (payload.flight_id,)
            ).fetchone()
            if flight is None:
                raise HTTPException(status_code=404, detail="Flight not found.")
            _ensure_capacity(connection, flight, payload.quantity)
            connection.execute(
                """
                INSERT INTO holds (id, user_id, flight_id, quantity, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    hold_id,
                    user["id"],
                    flight["id"],
                    payload.quantity,
                    now,
                    now + HOLD_LIFETIME_SECONDS,
                ),
            )
        return {
            "hold_id": hold_id,
            "flight_id": flight["id"],
            "quantity": payload.quantity,
            "total_price_cents": flight["base_fare_cents"] * payload.quantity,
            "currency": flight["currency"],
            "expires_at": now + HOLD_LIFETIME_SECONDS,
        }

    @app.post("/api/v3/bookings", status_code=201)
    def create_booking(
        payload: BookingRequest,
        request: Request,
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        if payload.quantity < 1:
            raise HTTPException(status_code=422, detail="Quantity must be between 1 and 9.")
        now = int(time.time())
        booking_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with connect_db(app.state.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            flight = connection.execute(
                "SELECT * FROM flights WHERE id = ?", (payload.flight_id,)
            ).fetchone()
            if flight is None:
                raise HTTPException(status_code=404, detail="Flight not found.")

            if payload.hold_id is not None:
                hold = connection.execute(
                    """
                    SELECT * FROM holds
                    WHERE id = ? AND user_id = ? AND status = 'active' AND expires_at > ?
                    """,
                    (payload.hold_id, user["id"], now),
                ).fetchone()
                if (
                    hold is None
                    or hold["flight_id"] != payload.flight_id
                    or hold["quantity"] != payload.quantity
                ):
                    raise HTTPException(status_code=409, detail="The hold is invalid or expired.")

            _ensure_capacity(connection, flight, payload.quantity, payload.hold_id)
            server_price_cents = flight["base_fare_cents"] * payload.quantity
            total_price_cents = server_price_cents
            if not request.state.flags["FIX_B2"] and payload.total_price is not None:
                total_price_cents = int(payload.total_price * 100)
            connection.execute(
                """
                INSERT INTO bookings (
                    id, agency_id, created_by_user_id, flight_id, hold_id,
                    traveler_name, passport_number, quantity, unit_price_cents,
                    total_price_cents, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'booked', ?)
                """,
                (
                    booking_id,
                    user["agency_id"],
                    user["id"],
                    flight["id"],
                    payload.hold_id,
                    payload.traveler_name.strip(),
                    payload.passport_number.strip(),
                    payload.quantity,
                    flight["base_fare_cents"],
                    total_price_cents,
                    created_at,
                ),
            )
            if payload.hold_id is not None:
                connection.execute(
                    "UPDATE holds SET status = 'used' WHERE id = ?",
                    (payload.hold_id,),
                )
            row = _get_visible_booking(connection, booking_id, user)
            assert row is not None
        return _booking_payload(row)

    @app.get("/api/v3/bookings/{booking_id}")
    def get_booking(
        booking_id: str, user: sqlite3.Row = user_dependency
    ) -> dict[str, Any]:
        with connect_db(app.state.db_path) as connection:
            row = _get_visible_booking(connection, booking_id, user)
        if row is None:
            raise HTTPException(status_code=404, detail="Booking not found.")
        return _booking_payload(row)

    @app.get("/api/v3/bookings/{booking_id}/invoice")
    def get_invoice(
        booking_id: str,
        request: Request,
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        if request.state.release_version != "v3.1":
            raise HTTPException(status_code=404, detail="Invoice not found.")

        with connect_db(app.state.db_path) as connection:
            if request.state.flags["FIX_B1"]:
                row = _get_visible_booking(connection, booking_id, user)
            else:
                row = connection.execute(
                    """
                    SELECT b.*, f.currency
                    FROM bookings AS b
                    JOIN flights AS f ON f.id = b.flight_id
                    WHERE b.id = ?
                    """,
                    (booking_id,),
                ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        return {
            "booking_id": row["id"],
            "agency_id": row["agency_id"],
            "traveler_name": row["traveler_name"],
            "total_price_cents": row["total_price_cents"],
            "currency": row["currency"],
        }

    @app.post("/api/v3/bookings/{booking_id}/pay")
    def pay_booking(
        booking_id: str, user: sqlite3.Row = user_dependency
    ) -> dict[str, Any]:
        _require_roles(user, "admin", "agent")
        with connect_db(app.state.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = _get_visible_booking(connection, booking_id, user)
            if row is None:
                raise HTTPException(status_code=404, detail="Booking not found.")
            if row["status"] != "booked":
                raise HTTPException(status_code=409, detail="Only an unpaid booking can be paid.")
            connection.execute(
                "UPDATE bookings SET status = 'paid' WHERE id = ? AND status = 'booked'",
                (booking_id,),
            )
            updated = _get_visible_booking(connection, booking_id, user)
            assert updated is not None
        return _booking_payload(updated)

    @app.post("/api/v3/bookings/{booking_id}/cancel")
    def cancel_booking(
        booking_id: str,
        request: Request,
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        _require_roles(user, "admin", "agent")
        with connect_db(app.state.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = _get_visible_booking(connection, booking_id, user)
            if row is None:
                raise HTTPException(status_code=404, detail="Booking not found.")
            if row["status"] == "cancelled" and request.state.flags["FIX_B3"]:
                raise HTTPException(status_code=409, detail="Booking is already cancelled.")
            if row["status"] == "cancelled":
                if row["refund_amount_cents"] > 0:
                    connection.execute(
                        """
                        UPDATE bookings
                        SET refund_amount_cents = refund_amount_cents + total_price_cents
                        WHERE id = ?
                        """,
                        (booking_id,),
                    )
                updated = _get_visible_booking(connection, booking_id, user)
                assert updated is not None
                return _booking_payload(updated)
            connection.execute(
                """
                UPDATE bookings
                SET status = 'cancelled',
                    refund_amount_cents = CASE
                        WHEN status = 'paid' THEN total_price_cents
                        ELSE 0
                    END
                WHERE id = ? AND status IN ('booked', 'paid')
                """,
                (booking_id,),
            )
            updated = _get_visible_booking(connection, booking_id, user)
            assert updated is not None
        return _booking_payload(updated)

    @app.get("/api/v3/users/me")
    def get_profile(user: sqlite3.Row = user_dependency) -> dict[str, Any]:
        return {"user": _account_payload(user)}

    @app.patch("/api/v3/users/me")
    def update_profile(
        update: ProfileUpdate,
        request: Request,
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        values = _validate_profile_update(update)
        if "role" in values and (
            request.state.flags["FIX_B5"] or values["role"] is None
        ):
            raise HTTPException(status_code=422, detail="Role cannot be updated.")
        allowed_columns = {"display_name", "email", "phone", "role"}
        if not set(values).issubset(allowed_columns):
            raise HTTPException(status_code=422, detail="Unsupported profile field.")
        assignments = ", ".join(f"{column} = ?" for column in values)
        with connect_db(app.state.db_path) as connection:
            connection.execute(
                f"UPDATE users SET {assignments} WHERE id = ?",
                (*values.values(), user["id"]),
            )
            updated = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
        assert updated is not None
        return {"user": _account_payload(updated)}

    @app.get("/api/v1/bookings/{booking_id}")
    def legacy_booking(booking_id: str, request: Request) -> dict[str, Any]:
        if request.state.flags["FIX_Z1"]:
            raise HTTPException(status_code=404, detail="Booking not found.")
        with connect_db(app.state.db_path) as connection:
            row = connection.execute(
                "SELECT id, passport_number FROM bookings WHERE id = ?",
                (booking_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Booking not found.")
        return {"id": row["id"], "passport_number": row["passport_number"]}

    @app.get("/api/v3/debug/config")
    def debug_config(
        request: Request, user: sqlite3.Row = user_dependency
    ) -> dict[str, Any]:
        del user
        if request.state.flags["FIX_Z2"]:
            raise HTTPException(status_code=404, detail="Not found.")
        return {
            "debug": True,
            "service": "SkyVoyage synthetic test app",
            "example_setting": "FAKE_ONLY_NOT_A_SECRET",
        }

    @app.get("/api/m/v2/fares")
    def mobile_fares(
        request: Request,
        user_agent: Annotated[str | None, Header()] = None,
        user: sqlite3.Row = user_dependency,
    ) -> dict[str, Any]:
        del user
        if user_agent is None or not re.search(
            r"iphone|ipad|ipod|android|mobile", user_agent, re.IGNORECASE
        ):
            raise HTTPException(status_code=404, detail="Fare route not found.")
        with connect_db(app.state.db_path) as connection:
            flights = connection.execute(
                "SELECT id, base_fare_cents, currency FROM flights ORDER BY id"
            ).fetchall()
        return {
            "fares": [
                {
                    "flight_id": flight["id"],
                    "fare_cents": flight["base_fare_cents"],
                    "currency": flight["currency"],
                }
                for flight in flights
            ]
        }

    @app.exception_handler(sqlite3.IntegrityError)
    async def database_constraint_error(
        request: Request, exc: sqlite3.IntegrityError
    ) -> Response:
        del request, exc
        return Response(
            content='{"detail":"Request violates a data constraint."}',
            status_code=409,
            media_type="application/json",
        )

    return app


app = create_app()
