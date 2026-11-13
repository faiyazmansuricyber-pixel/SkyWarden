from __future__ import annotations

import re

from engine.recon.paths import normalize_endpoint_path


ROUTE_LITERAL = re.compile(
    r"""(?P<quote>["'])(?P<path>/api/(?:v\d+|m/v\d+)/[^"'`\s]*)(?P=quote)"""
)
ROUTE_TEMPLATE = re.compile(
    r"""`(?P<prefix>/api/(?:v\d+|m/v\d+)/[^`]*?)\$\{[^}]+\}(?P<suffix>[^`]*)`"""
)


def extract_routes(source: str) -> set[str]:
    routes = {
        normalize_endpoint_path(match.group("path"))
        for match in ROUTE_LITERAL.finditer(source)
    }
    for match in ROUTE_TEMPLATE.finditer(source):
        template = f"{match.group('prefix')}{{id}}{match.group('suffix')}"
        normalized = normalize_endpoint_path(template)
        if not normalized.endswith("/"):
            routes.add(normalized)
    return {path for path in routes if path and path != "/"}
