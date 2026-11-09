"""Optional *ephemeral* Ladybug graph projection for Noosphere Lite.

The encrypted event journal remains authoritative. Ladybug is opened exclusively
as :memory: by this module: no plaintext sidecar is written to disk. Never
silently truncate a graph, never project memory bodies, and never claim that a
graph edge is verified evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from threading import RLock
from typing import Any

from .vault import MemoryVault
from .graph_plan import GraphPlanError, plan_graph, MAX_GRAPH_NODES, MAX_GRAPH_EDGES, MAX_BATCH_SIZE


class ProjectionError(RuntimeError):
    pass


NODE_SCHEMA = """CREATE NODE TABLE MemoryNode (
    id STRING PRIMARY KEY, title STRING, kind STRING, status STRING,
    epistemic_status STRING, source STRING, recorded_at STRING,
    intent STRING, evidence_ref STRING
)"""
EDGE_SCHEMA = """CREATE REL TABLE MemoryEdge (
    FROM MemoryNode TO MemoryNode,
    relation STRING, recorded_at STRING, epistemic_status STRING,
    origin STRING, intent STRING, evidence_ref STRING
)"""
RECEIPT_SCHEMA = """CREATE NODE TABLE ProjectionReceipt (
    id STRING PRIMARY KEY, journal_seq INT64, journal_digest STRING,
    projection_hash STRING, node_count INT64, edge_count INT64
)"""

CREATE_NODE = """UNWIND $rows AS row CREATE (:MemoryNode {
    id: row.id, title: row.title, kind: row.kind, status: row.status,
    epistemic_status: row.epistemic_status, source: row.source,
    recorded_at: row.recorded_at, intent: row.intent,
    evidence_ref: row.evidence_ref
})"""
CREATE_EDGE = """UNWIND $rows AS row
MATCH (a:MemoryNode), (b:MemoryNode)
WHERE a.id = row.src AND b.id = row.dst
CREATE (a)-[:MemoryEdge {
    relation: row.relation, recorded_at: row.recorded_at,
    epistemic_status: row.epistemic_status,
    origin: row.origin, intent: row.intent, evidence_ref: row.evidence_ref
}]->(b)"""
CREATE_RECEIPT = """CREATE (:ProjectionReceipt {
    id: 'primary', journal_seq: $journal_seq, journal_digest: $journal_digest,
    projection_hash: $projection_hash, node_count: $node_count,
    edge_count: $edge_count
})"""


@dataclass(frozen=True)
class ProjectionStatus:
    journal_seq: int
    journal_digest: str
    projection_hash: str
    node_count: int
    edge_count: int
    refreshed: bool


def _value(value: Any) -> str:
    """Keep optional metadata strings; no plaintext bodies are exported."""
    return value if isinstance(value, str) else ""


def _execute(conn: Any, statement: str, params: dict | None = None):
    if params is None:
        return conn.execute(statement)
    return conn.execute(statement, parameters=params)


def _serialized(method):
    """Serialize all access to the shared Ladybug connection."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._guard:
            return method(self, *args, **kwargs)
    return guarded


class InMemoryLadybugProjection:
    """Ephemeral sidecar with transactional replace + journal checkpoints.

    The constructor creates an in-memory database. The public class does not
    accept filesystem paths or existing connections, intentionally preventing
    accidental persistent plaintext graph databases.

    Metadata such as titles and sources may be sensitive even without bodies.
    Keep this object process-local and restrict access to its query results.
    """

    def __init__(self, vault: MemoryVault, *, limit: int = MAX_GRAPH_NODES,
                 edge_limit: int = MAX_GRAPH_EDGES, batch_size: int = 256):
        for name, value, maximum in (
            ("limit", limit, MAX_GRAPH_NODES),
            ("edge_limit", edge_limit, MAX_GRAPH_EDGES),
            ("batch_size", batch_size, MAX_BATCH_SIZE),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ProjectionError(f"{name} must be 1..{maximum}")
        try:
            import ladybug as lb
        except ImportError as exc:
            raise ProjectionError("optional dependency 'ladybug' is not installed") from exc
        self._guard = RLock()
        self.vault = vault
        self.limit = limit
        self.edge_limit = edge_limit
        self.batch_size = batch_size
        self._db = lb.Database(":memory:")
        self._conn = lb.Connection(self._db)
        for ddl in (NODE_SCHEMA, EDGE_SCHEMA, RECEIPT_SCHEMA):
            _execute(self._conn, ddl)

    def _receipt(self) -> tuple | None:
        rows = _execute(
            self._conn,
            "MATCH (r:ProjectionReceipt) RETURN r.journal_seq, "
            "r.journal_digest, r.projection_hash, r.node_count, r.edge_count",
        ).get_all()
        if len(rows) > 1:
            raise ProjectionError("multiple projection receipts")
        return tuple(rows[0]) if rows else None

    def _counts(self) -> tuple[int, int]:
        """Detect accidental external mutation of the materialized rows."""
        node_count = _execute(
            self._conn, "MATCH (n:MemoryNode) RETURN COUNT(n)"
        ).get_all()[0][0]
        edge_count = _execute(
            self._conn, "MATCH ()-[e:MemoryEdge]->() RETURN COUNT(e)"
        ).get_all()[0][0]
        return int(node_count), int(edge_count)

    @_serialized
    def status(self) -> dict:
        receipt = self._receipt()
        if receipt is None:
            return {"available": True, "initialized": False, "persistent": False}
        return {
            "available": True,
            "initialized": True,
            "persistent": False,
            "journal_seq": receipt[0],
            "journal_digest": receipt[1],
            "projection_hash": receipt[2],
            "node_count": receipt[3],
            "edge_count": receipt[4],
        }

    @_serialized
    def sync(self) -> ProjectionStatus:
        """Refresh atomically or leave old projection intact on failure.

        Incremental event projection is not assumed safe across journal
        recovery; this deliberately does bounded full rebuilds.
        """
        # Read the encrypted journal exactly once and freeze its checkpoint.
        # A later writer may advance the journal; this sync is snapshot-consistent.
        source = self.vault._snapshot()
        try:
            plan = plan_graph(
                source, max_nodes=self.limit, max_edges=self.edge_limit,
            )
        except GraphPlanError as exc:
            raise ProjectionError(str(exc)) from exc
        seq = plan.journal_seq
        digest = plan.journal_digest
        projection_hash = plan.projection_hash
        checkpoint = (seq, digest, projection_hash, plan.node_count, plan.edge_count)
        current = self._receipt()
        if current == checkpoint and self._counts() == (plan.node_count, plan.edge_count):
            return ProjectionStatus(*checkpoint, refreshed=False)
        _execute(self._conn, "BEGIN TRANSACTION")
        try:
            _execute(self._conn, "MATCH (n:MemoryNode) DETACH DELETE n")
            _execute(self._conn, "MATCH (r:ProjectionReceipt) DELETE r")
            for nodes in plan.node_batches(self.batch_size):
                rows = [{
                    "id": n["id"], "title": _value(n.get("title")),
                    "kind": _value(n.get("kind")), "status": _value(n.get("status")),
                    "epistemic_status": _value(n.get("epistemic_status")),
                    "source": _value(n.get("source")),
                    "recorded_at": _value(n.get("recorded_at")),
                    "intent": _value(n.get("intent")),
                    "evidence_ref": _value(n.get("evidence_ref")),
                } for n in nodes]
                _execute(self._conn, CREATE_NODE, {"rows": rows})
            for edges in plan.edge_batches(self.batch_size):
                rows = []
                for e in edges:
                    qualifiers = e.get("qualifiers") or {}
                    rows.append({
                        "src": e["from"], "dst": e["to"],
                        "relation": e["relation"],
                        "recorded_at": _value(e.get("recorded_at")),
                        "epistemic_status": _value(qualifiers.get("epistemic_status"))
                        or "unreviewed",
                        "origin": _value(qualifiers.get("origin")),
                        "intent": _value(qualifiers.get("intent")),
                        "evidence_ref": _value(qualifiers.get("evidence_ref")),
                    })
                _execute(self._conn, CREATE_EDGE, {"rows": rows})
            _execute(self._conn, CREATE_RECEIPT, {
                "journal_seq": seq, "journal_digest": digest,
                "projection_hash": projection_hash,
                "node_count": plan.node_count, "edge_count": plan.edge_count,
            })
            _execute(self._conn, "COMMIT")
        except Exception:
            try:
                _execute(self._conn, "ROLLBACK")
            except Exception:
                pass
            raise
        return ProjectionStatus(*checkpoint, refreshed=True)

    @_serialized
    def paths(self, memory_id: str, *, depth: int = 3,
              direction: str = "both", relation: str = "",
              max_nodes: int = 200, max_edges: int = 400) -> dict:
        """Bounded breadth-first relationship exploration (1-4 hops).

        Uses fixed Cypher fragments and parameter bindings, not user-written
        Cypher. A budget hit is flagged as truncated, never hidden.
        """
        if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 4:
            raise ProjectionError("depth must be 1..4")
        if direction not in {"in", "out", "both"}:
            raise ProjectionError("direction must be in/out/both")
        if not isinstance(memory_id, str) or not memory_id or len(memory_id) > 128:
            raise ProjectionError("invalid memory ID")
        if not isinstance(relation, str) or len(relation) > 64:
            raise ProjectionError("invalid relation")
        for value, maximum, name in ((max_nodes, 200, "max_nodes"),
                                     (max_edges, 400, "max_edges")):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ProjectionError(f"{name} must be 1..{maximum}")
        if self._receipt() is None:
            raise ProjectionError("sidecar must be synchronized before traversal")

        lookup = """MATCH (n:MemoryNode) WHERE n.id IN $ids
                    RETURN n.id, n.title, n.kind, n.status, n.epistemic_status"""
        def attributes(ids):
            rows = _execute(self._conn, lookup, {"ids": sorted(ids)}).get_all()
            return {r[0]: {
                "id": r[0], "title": r[1], "kind": r[2],
                "status": r[3], "epistemic_status": r[4],
            } for r in rows}
        base = attributes({memory_id})
        if memory_id not in base:
            raise ProjectionError("memory ID missing from current projection")
        visited = {memory_id}
        frontier = {memory_id}
        node_details = {memory_id: dict(base[memory_id], distance=0)}
        selected = {}
        truncated = False
        clause = {
            "out": "a.id IN $frontier",
            "in": "b.id IN $frontier",
            "both": "(a.id IN $frontier OR b.id IN $frontier)",
        }[direction]
        query = f"""MATCH (a:MemoryNode)-[e:MemoryEdge]->(b:MemoryNode)
            WHERE {clause} AND ($relation = '' OR e.relation = $relation)
            RETURN a.id, b.id, e.relation, e.epistemic_status,
                   e.origin, e.intent, e.evidence_ref
            ORDER BY a.id, b.id, e.relation LIMIT {max_edges + 1}"""
        for distance in range(1, depth + 1):
            if not frontier:
                break
            rows = _execute(self._conn, query, {
                "frontier": sorted(frontier), "relation": relation,
            }).get_all()
            next_frontier = set()
            for row in rows:
                a, b, rel = row[:3]
                key = (a, b, rel)
                if key in selected:
                    continue
                neighbor = b if a in frontier and direction != "in" else a
                if neighbor not in visited and len(visited) >= max_nodes:
                    truncated = True
                    continue
                if len(selected) >= max_edges:
                    truncated = True
                    break
                selected[key] = {
                    "from": a, "to": b, "relation": rel,
                    "epistemic_status": row[3], "origin": row[4],
                    "intent": row[5], "evidence_ref": row[6],
                    "evidence_verified": False,
                }
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
            if len(rows) > max_edges:
                truncated = True
            node_details.update({
                ident: dict(metadata, distance=distance)
                for ident, metadata in attributes(next_frontier).items()
            })
            frontier = next_frontier
            if len(selected) >= max_edges:
                truncated = True
                break
        return {
            "origin": memory_id, "depth": depth, "direction": direction,
            "relation": relation or None, "truncated": truncated,
            "nodes": [node_details[i] for i in sorted(node_details)],
            "links": [selected[k] for k in sorted(selected)],
            "evidence_verified": False,
        }

    @_serialized
    def neighbors(self, memory_id: str, *, direction: str = "both") -> list[dict]:
        """Bounded, read-only, one-hop traversal with original edge direction."""
        if direction not in {"in", "out", "both"}:
            raise ProjectionError("direction must be in/out/both")
        if not isinstance(memory_id, str) or not memory_id:
            raise ProjectionError("invalid memory ID")
        if self._receipt() is None:
            raise ProjectionError("sidecar must be synchronized before traversal")
        clause = {
            "out": "a.id = $memory_id",
            "in": "b.id = $memory_id",
            "both": "(a.id = $memory_id OR b.id = $memory_id)",
        }[direction]
        # The only dynamically interpolated text is from the fixed mapping.
        query = f"""MATCH (a:MemoryNode)-[e:MemoryEdge]->(b:MemoryNode)
            WHERE {clause}
            RETURN a.id, b.id, e.relation, e.epistemic_status,
                   e.origin, e.intent, e.evidence_ref
            ORDER BY a.id, b.id, e.relation LIMIT 200"""
        rows = _execute(self._conn, query, {"memory_id": memory_id}).get_all()
        return [{
            "from": row[0], "to": row[1], "relation": row[2],
            "epistemic_status": row[3], "origin": row[4],
            "intent": row[5], "evidence_ref": row[6],
            "evidence_verified": False,
        } for row in rows]


def register_mcp_tools(app: Any, vault: MemoryVault) -> None:
    """Register explicit opt-in graph methods on a process-local graph."""
    from dataclasses import asdict

    sidecar = InMemoryLadybugProjection(vault)

    @app.tool()
    def memory_ladybug_sync() -> dict:
        """Catch up the ephemeral graph from the authoritative encrypted vault."""
        return asdict(sidecar.sync())

    @app.tool()
    def memory_ladybug_status() -> dict:
        """Show last graph checkpoint; not proof of independent fact verification."""
        return sidecar.status()

    @app.tool()
    def memory_ladybug_paths(memory_id: str, depth: int = 3,
                             direction: str = "both", relation: str = "",
                             max_nodes: int = 200, max_edges: int = 400) -> dict:
        """Refresh, then explore a bounded 1-4 hop directed relation graph."""
        # Keep refresh + traversal on the very same graph checkpoint.
        with sidecar._guard:
            checkpoint = sidecar.sync()
            results = sidecar.paths(memory_id, depth=depth, direction=direction,
                                    relation=relation, max_nodes=max_nodes,
                                    max_edges=max_edges)
        return {
            **results,
            "journal_seq": checkpoint.journal_seq,
            "projection_hash": checkpoint.projection_hash,
        }

    @app.tool()
    def memory_ladybug_neighbors(memory_id: str,
                                 direction: str = "both") -> dict:
        """Sync first, then traverse typed directed edges (bounded to 200)."""
        with sidecar._guard:
            checkpoint = sidecar.sync()
            return {
                "journal_seq": checkpoint.journal_seq,
                "projection_hash": checkpoint.projection_hash,
                "edges": sidecar.neighbors(memory_id, direction=direction),
                "claims_verified": False,
            }
