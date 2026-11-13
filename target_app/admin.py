from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from target_app.db import (
    DEFAULT_DB_PATH,
    connect_db,
    initialize_database,
    read_release_flags,
)


AdminFlag = Literal[
    "FIX_B1",
    "FIX_B2",
    "FIX_B3",
    "FIX_B4",
    "FIX_B5",
    "FIX_Z1",
    "FIX_Z2",
    "FIX_S1",
]


class StrictAdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseUpdate(StrictAdminModel):
    version: Literal["v3.0", "v3.1"]


class FlagUpdate(StrictAdminModel):
    flag: AdminFlag
    enabled: bool


def _require_loopback(request: Request) -> None:
    if request.client is None:
        raise HTTPException(status_code=403, detail="Loopback access is required.")
    try:
        remote = ipaddress.ip_address(request.client.host)
    except ValueError as error:
        raise HTTPException(
            status_code=403, detail="Loopback access is required."
        ) from error
    mapped_address = getattr(remote, "ipv4_mapped", None)
    is_loopback = remote.is_loopback or (
        mapped_address is not None and mapped_address.is_loopback
    )
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Loopback access is required.")


def create_admin_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    initialize_database(db_path)
    app = FastAPI(
        title="SkyVoyage local admin",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.db_path = db_path

    @app.get("/__admin/state")
    def get_state(request: Request) -> dict[str, object]:
        _require_loopback(request)
        release_version, flags = read_release_flags(app.state.db_path)
        return {"release_version": release_version, "flags": flags}

    @app.put("/__admin/release")
    def set_release(update: ReleaseUpdate, request: Request) -> dict[str, object]:
        _require_loopback(request)
        with connect_db(app.state.db_path) as connection:
            connection.execute(
                "UPDATE release_flags SET release_version = ? WHERE id = 1",
                (update.version,),
            )
        release_version, flags = read_release_flags(app.state.db_path)
        return {"release_version": release_version, "flags": flags}

    @app.patch("/__admin/flags")
    def set_flag(update: FlagUpdate, request: Request) -> dict[str, object]:
        _require_loopback(request)
        with connect_db(app.state.db_path) as connection:
            row = connection.execute(
                "SELECT flags_json FROM release_flags WHERE id = 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("The SkyVoyage release/flags row is missing.")
            flags = json.loads(row["flags_json"])
            flags[update.flag] = update.enabled
            connection.execute(
                "UPDATE release_flags SET flags_json = ? WHERE id = 1",
                (json.dumps(flags, sort_keys=True),),
            )
        release_version, flags = read_release_flags(app.state.db_path)
        return {"release_version": release_version, "flags": flags}

    return app


app = create_admin_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
