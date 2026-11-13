from __future__ import annotations

import networkx as nx

from engine.kb.db import KnowledgeBase


class EndpointGraph:
    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self.knowledge_base = knowledge_base
        self.graph = nx.MultiDiGraph()
        self.refresh()

    @staticmethod
    def node_id(method: str, path: str) -> str:
        return f"{method.upper()} {path}"

    def refresh(self) -> None:
        self.graph.clear()
        for endpoint in self.knowledge_base.endpoints():
            node_id = self.node_id(endpoint["method"], endpoint["path"])
            self.graph.add_node(node_id, **endpoint)
        for edge in self.knowledge_base.edges():
            source = self.node_id(edge["source_method"], edge["source_path"])
            target = self.node_id(edge["target_method"], edge["target_path"])
            self.graph.add_edge(source, target, relation=edge["relation"])

    def as_dict(self) -> dict[str, list[dict[str, object]]]:
        nodes = [
            {"id": node_id, **attributes}
            for node_id, attributes in self.graph.nodes(data=True)
        ]
        edges = [
            {"source": source, "target": target, **attributes}
            for source, target, attributes in self.graph.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}
