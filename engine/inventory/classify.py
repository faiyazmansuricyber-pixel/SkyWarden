from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from engine.kb.db import KnowledgeBase
from engine.recon.paths import normalize_endpoint_path
from engine.recon.prober import ProbeResult


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TRAFFIC_PATH = ROOT_DIR / "data" / "access_logs.jsonl"
DEFAULT_OWNERS_PATH = Path(__file__).resolve().parent / "owners.yaml"


@dataclass
class TrafficSummary:
    method: str
    path: str
    last_traffic: datetime
    latest_status: int
    roles: set[str] = field(default_factory=set)
    sample_paths: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class InventoryItem:
    method: str
    path: str
    classification: str
    reachable: bool
    status_code: int | None
    last_traffic: str | None
    auth_required: bool | None
    data_exposed: tuple[str, ...]
    owner: str
    recommendation: str
    roles: tuple[str, ...]
    sources: tuple[str, ...]


def load_traffic(path: Path = DEFAULT_TRAFFIC_PATH) -> dict[tuple[str, str], TrafficSummary]:
    summaries: dict[tuple[str, str], TrafficSummary] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
                timestamp_value = record["ts"]
                method = record["method"].upper()
                raw_path = record["path"]
                status = int(record["status"])
                role = str(record["role"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid traffic record on line {line_number}.") from error
            try:
                timestamp = datetime.fromisoformat(
                    str(timestamp_value).replace("Z", "+00:00")
                )
            except ValueError as error:
                raise ValueError(f"Invalid traffic timestamp on line {line_number}.") from error
            if timestamp.tzinfo is None:
                raise ValueError(f"Traffic timestamp on line {line_number} has no timezone.")
            normalized_path = normalize_endpoint_path(str(raw_path))
            key = (method, normalized_path)
            summary = summaries.get(key)
            if summary is None:
                summaries[key] = TrafficSummary(
                    method=method,
                    path=normalized_path,
                    last_traffic=timestamp.astimezone(timezone.utc),
                    latest_status=status,
                    roles={role},
                    sample_paths={urlsplit(str(raw_path)).path},
                )
                continue
            summary.roles.add(role)
            summary.sample_paths.add(urlsplit(str(raw_path)).path)
            if timestamp > summary.last_traffic:
                summary.last_traffic = timestamp.astimezone(timezone.utc)
                summary.latest_status = status
    return summaries


def load_owners(path: Path = DEFAULT_OWNERS_PATH) -> dict[str, str]:
    owners: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        prefix, separator, owner = entry.partition(":")
        if not separator or not owner.strip():
            raise ValueError(f"Invalid owner mapping on line {line_number}.")
        owners[prefix.strip().strip("\"'")] = owner.strip()
    return owners


def _owner_for_path(path: str, owners: dict[str, str]) -> str:
    matching = [prefix for prefix in owners if path.startswith(prefix)]
    if not matching:
        return "Unassigned"
    return owners[max(matching, key=len)]


def _default_recommendation(classification: str) -> str:
    if classification == "zombie":
        return "Decommission or restrict the endpoint and verify no consumers remain."
    if classification == "shadow":
        return "Document the API and confirm its authentication and ownership policy."
    return "Maintain the endpoint contract and monitor its traffic and access controls."


def classify_inventory(
    traffic: dict[tuple[str, str], TrafficSummary],
    observations: list[ProbeResult],
    discovered_paths: set[str],
    *,
    owners_path: Path = DEFAULT_OWNERS_PATH,
) -> list[InventoryItem]:
    normalized_discovered = {
        normalize_endpoint_path(path) for path in discovered_paths
    }
    probes = {(result.method.upper(), result.path): result for result in observations}
    endpoint_keys = set(traffic) | set(probes)
    owners = load_owners(owners_path)
    items: list[InventoryItem] = []

    for method, path in sorted(endpoint_keys, key=lambda value: (value[1], value[0])):
        traffic_summary = traffic.get((method, path))
        probe = probes.get((method, path))
        reachable = (
            probe.reachable
            if probe is not None
            else traffic_summary is not None and traffic_summary.latest_status < 400
        )
        if not reachable:
            continue

        if traffic_summary is None:
            classification = "zombie"
        elif path not in normalized_discovered:
            classification = "shadow"
        else:
            classification = "active"

        if probe is not None:
            auth_required: bool | None = probe.auth_required
            data_exposed = probe.data_exposed
            status_code = probe.status_code
        elif traffic_summary is not None:
            auth_required = any(
                role in {"admin", "agent", "subagent"}
                for role in traffic_summary.roles
            )
            data_exposed = ()
            status_code = traffic_summary.latest_status
        else:
            auth_required = None
            data_exposed = ()
            status_code = None

        sources = []
        if traffic_summary is not None:
            sources.append("traffic")
        if path in normalized_discovered:
            sources.append("web crawl or JavaScript bundle")
        if probe is not None:
            sources.append("safety-gated probe")
        items.append(
            InventoryItem(
                method=method,
                path=path,
                classification=classification,
                reachable=reachable,
                status_code=status_code,
                last_traffic=(
                    traffic_summary.last_traffic.isoformat()
                    if traffic_summary is not None
                    else None
                ),
                auth_required=auth_required,
                data_exposed=tuple(sorted(data_exposed)),
                owner=_owner_for_path(path, owners),
                recommendation=_default_recommendation(classification),
                roles=(
                    tuple(sorted(traffic_summary.roles))
                    if traffic_summary is not None
                    else ()
                ),
                sources=tuple(sources),
            )
        )
    return items


def persist_inventory(
    items: list[InventoryItem],
    knowledge_base: KnowledgeBase,
) -> None:
    for item in items:
        record = asdict(item)
        record["data_exposed"] = list(item.data_exposed)
        record["roles"] = list(item.roles)
        record["sources"] = list(item.sources)
        knowledge_base.upsert_endpoint(record)
