from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.inventory.classify import (
    DEFAULT_OWNERS_PATH,
    DEFAULT_TRAFFIC_PATH,
    InventoryItem,
    classify_inventory,
    load_traffic,
    persist_inventory,
)
from engine.inventory.openapi_gen import DEFAULT_OPENAPI_PATH, write_openapi
from engine.kb.db import DEFAULT_DB_PATH, KnowledgeBase
from engine.kb.graph import EndpointGraph
from engine.recon.crawler import CrawlResult, crawl_roles
from engine.recon.prober import ProbeResult, build_probe_candidates, probe_candidates
from engine.safety.gate import SafetyGate
from engine.safety.vault import Vault


@dataclass(frozen=True)
class ReconInventoryResult:
    crawls: tuple[CrawlResult, ...]
    probes: tuple[ProbeResult, ...]
    inventory: tuple[InventoryItem, ...]
    graph: dict[str, list[dict[str, object]]]
    openapi_path: Path


def run_recon_inventory(
    gate: SafetyGate,
    vault: Vault,
    *,
    traffic_path: Path = DEFAULT_TRAFFIC_PATH,
    owners_path: Path = DEFAULT_OWNERS_PATH,
    har_dir: Path | None = None,
    database_path: Path = DEFAULT_DB_PATH,
    openapi_path: Path = DEFAULT_OPENAPI_PATH,
    account_names: set[str] | None = None,
) -> ReconInventoryResult:
    traffic = load_traffic(traffic_path)
    sample_paths = {
        sample_path
        for summary in traffic.values()
        for sample_path in summary.sample_paths
    }
    candidates = build_probe_candidates(sample_paths)

    if har_dir is not None and account_names is not None:
        crawls = crawl_roles(
            gate,
            vault,
            har_dir=har_dir,
            account_names=account_names,
        )
    elif har_dir is not None:
        crawls = crawl_roles(gate, vault, har_dir=har_dir)
    elif account_names is not None:
        crawls = crawl_roles(gate, vault, account_names=account_names)
    else:
        crawls = crawl_roles(gate, vault)
    discovered_paths = {
        path for crawl in crawls for path in crawl.discovered_paths
    }
    probes = probe_candidates(gate, vault, candidates)
    items = classify_inventory(
        traffic,
        probes,
        discovered_paths,
        owners_path=owners_path,
    )

    knowledge_base = KnowledgeBase(database_path)
    persist_inventory(items, knowledge_base)
    for crawl in crawls:
        requests = crawl.requests
        for previous, current in zip(requests, requests[1:]):
            knowledge_base.add_edge(
                str(previous["method"]),
                str(previous["path"]),
                str(current["method"]),
                str(current["path"]),
                relation="observed_role_flow",
            )
    graph = EndpointGraph(knowledge_base).as_dict()
    write_openapi(items, openapi_path)
    return ReconInventoryResult(
        crawls=tuple(crawls),
        probes=tuple(probes),
        inventory=tuple(items),
        graph=graph,
        openapi_path=openapi_path,
    )
