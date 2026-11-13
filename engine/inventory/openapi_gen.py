from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from engine.inventory.classify import InventoryItem


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OPENAPI_PATH = ROOT_DIR / "data" / "openapi.json"
HTTP_METHODS = {
    "DELETE",
    "GET",
    "HEAD",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
}


def build_openapi(items: list[InventoryItem]) -> dict[str, Any]:
    paths: dict[str, dict[str, object]] = {}
    for item in items:
        method = item.method.lower()
        if method.upper() not in HTTP_METHODS:
            continue
        path_item = paths.setdefault(item.path, {})
        operation: dict[str, object] = {
            "operationId": re.sub(r"[^A-Za-z0-9]+", "_", f"{method}_{item.path}").strip("_"),
            "summary": f"{method.upper()} {item.path}",
            "responses": {
                "200": {"description": "Successful response"},
                "default": {"description": "Target response"},
            },
            "x-skywarden-classification": item.classification,
            "x-skywarden-owner": item.owner,
        }
        path_parameters = re.findall(r"\{([^}]+)\}", item.path)
        if path_parameters:
            operation["parameters"] = [
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
                for name in path_parameters
            ]
        if item.auth_required:
            operation["security"] = [{"BearerAuth": []}]
        path_item[method] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "SkyVoyage discovered API",
            "version": "3.0",
            "description": "Generated from the local synthetic app's observed traffic and gated recon.",
        },
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"}
            }
        },
    }


def write_openapi(
    items: list[InventoryItem],
    output_path: Path = DEFAULT_OPENAPI_PATH,
) -> dict[str, Any]:
    document = build_openapi(items)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return document
