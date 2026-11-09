"""Optional *ephemeral* Ladybug graph projection for Noosphere Lite.

The encrypted event journal remains authoritative. Ladybug is opened exclusively
as :memory: by this module: no plaintext sidecar is written to disk. Never
silently truncate a graph, never project memory bodies, and never claim that a
graph edge is verified evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .vault import MemoryVault


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

CREATE_NODE = """CREATE (:MemoryNode {
    id: $id, title: $title, kind: $kind, status: $status,
    epistemic_status: $epistemic_status, source: $source,
    recorded_at: $recorded_at, intent: $intent, evidence_ref: $evidence_ref
})"""
CREATE_EDGE = """MATCH (a:MemoryNode), (b:MemoryNode)
WHERE a.id = $src AND b.id = $dst
CREATE (a)-[:MemoryEdge {
    relation: $relation, recorded_at: $recorded_at,
    epistemic_status: $epistemic_status,
    origin: $origin, intent: $intent, evidence_ref: $evidence_ref
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


class InMemoryLadybugProjection:
    """Ephemeral sidecar with transactional replace + journal checkpoints.

    The constructor creates an in-memory database. The public class does not
    accept filesystem paths or existing connections, intentionally preventing
    accidental persistent plaintext graph databases.

    Metadata such as titles and sources may be sensitive even without bodies.
    Keep this object process-local and restrict access to its query results.
    """

    def __init__(self, vault: MemoryVault, *, limit: int = 1000):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ProjectionError("limit must be 1..1000")
        try:
            import ladybug as lb
        except ImportError as exc:
            raise ProjectionError("optional dependency 'ladybug' is not installed") from exc
        self.vault = vault
        self.limit = limit
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

    def sync(self) -> ProjectionStatus:
        """Refresh atomically or leave old projection intact on failure.

        Incremental event projection is not assumed safe across journal
        recovery; this deliberately does bounded full rebuilds.
        """
        snapshot = self.vault.graph_projection(limit=self.limit)
        if snapshot["truncated"]:
            raise ProjectionError(
                "journal graph exceeds safe projection limit; refusing partial sync"
            )
        seq = snapshot["journal_seq"]
        digest = snapshot["journal_digest"]
        projection_hash = snapshot["projection_hash"]
        nodes = snapshot["nodes"]
        edges = snapshot["links"]
        checkpoint = (seq, digest, projection_hash, len(nodes), len(edges))
        current = self._receipt()
        if current == checkpoint and self._counts() == (len(nodes), len(edges)):
            return ProjectionStatus(*checkpoint, refreshed=False)
        _execute(self._conn, "BEGIN TRANSACTION")
        try:
            _execute(self._conn, "MATCH (n:MemoryNode) DETACH DELETE n")
            _execute(self._conn, "MATCH (r:ProjectionReceipt) DELETE r")
            for n in nodes:
                _execute(self._conn, CREATE_NODE, {
                    "id": n["id"], "title": _value(n.get("title")),
                    "kind": _value(n.get("kind")), "status": _value(n.get("status")),
                    "epistemic_status": _value(n.get("epistemic_status")),
                    "source": _value(n.get("source")),
                    "recorded_at": _value(n.get("recorded_at")),
                    "intent": _value(n.get("intent")),
                    "evidence_ref": _value(n.get("evidence_ref")),
                })
            for e in edges:
                qualifiers = e.get("qualifiers") or {}
                _execute(self._conn, CREATE_EDGE, {
                    "src": e["from"], "dst": e["to"],
                    "relation": e["relation"],
                    "recorded_at": _value(e.get("recorded_at")),
                    "epistemic_status": _value(qualifiers.get("epistemic_status"))
                    or "unreviewed",
                    "origin": _value(qualifiers.get("origin")),
                    "intent": _value(qualifiers.get("intent")),
                    "evidence_ref": _value(qualifiers.get("evidence_ref")),
                })
            _execute(self._conn, CREATE_RECEIPT, {
                "journal_seq": seq, "journal_digest": digest,
                "projection_hash": projection_hash,
                "node_count": len(nodes), "edge_count": len(edges),
            })
            _execute(self._conn, "COMMIT")
        except Exception:
            try:
                _execute(self._conn, "ROLLBACK")
            except Exception:
                pass
            raise
        return ProjectionStatus(*checkpoint, refreshed=True)

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
    """Register the three explicit opt-in methods on a process-local graph."""
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
    def memory_ladybug_neighbors(memory_id: str,
                                 direction: str = "both") -> dict:
        """Sync first, then traverse typed directed edges (bounded to 200)."""
        checkpoint = sidecar.sync()
        return {
            "journal_seq": checkpoint.journal_seq,
            "projection_hash": checkpoint.projection_hash,
            "edges": sidecar.neighbors(memory_id, direction=direction),
            "claims_verified": False,
        }
