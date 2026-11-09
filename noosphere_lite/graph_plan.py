"""Snapshot-consistent, bounded-memory graph planning for ephemeral sidecars.

Only the source vault's existing decrypted in-memory Snapshot is inspected.
Projected metadata is materialized in bounded chunks. No open index is persisted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterator

from .knowledge_evolution import projection_node, projection_edge

MAX_GRAPH_NODES = 50_000
MAX_GRAPH_EDGES = 500_000
MAX_BATCH_SIZE = 1_000


class GraphPlanError(ValueError):
    pass


def _check_int(value: int, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GraphPlanError(f"{name} must be {minimum}..{maximum}")
    return value


def _encode(document: dict) -> bytes:
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True)
class GraphPlan:
    """Immutable identity of a single authoritative journal snapshot.

    The original vault snapshot is already entirely in RAM. This plan stores
    only ordered node IDs and edge keys rather than a second complete graph.
    """
    snapshot: object
    node_ids: tuple[str, ...]
    edge_keys: tuple[tuple[str, str, str], ...]
    projection_hash: str

    @property
    def journal_seq(self) -> int:
        return self.snapshot.seq

    @property
    def journal_digest(self) -> str:
        return self.snapshot.digest.hex()

    @property
    def node_count(self) -> int:
        return len(self.node_ids)

    @property
    def edge_count(self) -> int:
        return len(self.edge_keys)

    def node_batches(self, batch_size: int) -> Iterator[list[dict]]:
        batch_size = _check_int(batch_size, 1, MAX_BATCH_SIZE, "batch_size")
        for offset in range(0, self.node_count, batch_size):
            yield [projection_node(self.snapshot.nodes[key])
                   for key in self.node_ids[offset:offset + batch_size]]

    def edge_batches(self, batch_size: int) -> Iterator[list[dict]]:
        batch_size = _check_int(batch_size, 1, MAX_BATCH_SIZE, "batch_size")
        for offset in range(0, self.edge_count, batch_size):
            yield [projection_edge(self.snapshot, key)
                   for key in self.edge_keys[offset:offset + batch_size]]


def plan_graph(snapshot, *, max_nodes: int = MAX_GRAPH_NODES,
               max_edges: int = MAX_GRAPH_EDGES) -> GraphPlan:
    """Create a deterministic full-graph hash without building JSON arrays.

    Uses the same canonical serialized representation as project_snapshot()
    so hashes are byte-for-byte compatible for small graphs.
    Reject excess nodes and edges before any graph writes; never truncate.
    """
    _check_int(max_nodes, 1, MAX_GRAPH_NODES, "max_nodes")
    _check_int(max_edges, 1, MAX_GRAPH_EDGES, "max_edges")
    node_ids = tuple(sorted(
        key for key, node in snapshot.nodes.items() if not node.get("archived")
    ))
    if len(node_ids) > max_nodes:
        raise GraphPlanError(f"active node count exceeds max_nodes={max_nodes}")
    node_set = set(node_ids)
    edge_keys = tuple(sorted(
        key for key in snapshot.links
        if key[0] in node_set and key[1] in node_set
    ))
    if len(edge_keys) > max_edges:
        raise GraphPlanError(f"active edge count exceeds max_edges={max_edges}")

    h = hashlib.sha256()
    h.update(b'{"links":[')
    for i, key in enumerate(edge_keys):
        if i:
            h.update(b",")
        h.update(_encode(projection_edge(snapshot, key)))
    h.update(b'],"nodes":[')
    for i, key in enumerate(node_ids):
        if i:
            h.update(b",")
        h.update(_encode(projection_node(snapshot.nodes[key])))
    h.update(b"]}")
    return GraphPlan(snapshot, node_ids, edge_keys, h.hexdigest())
