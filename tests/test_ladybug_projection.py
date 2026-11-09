"""Real Ladybug integration tests; skipped if optional package is absent."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from noosphere_lite.ladybug_projection import (
    InMemoryLadybugProjection, ProjectionError, CREATE_EDGE, register_mcp_tools,
)
from noosphere_lite.vault import MemoryVault


@unittest.skipUnless(importlib.util.find_spec("ladybug") is not None,
                     "optional LadybugDB not installed")
class LadybugProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = MemoryVault(
            self.root / "primary", self.root / "mirror",
            self.root / "keys" / "key", allow_same_device=True,
        )
        self.vault.initialize()
        self.a = self.vault.add(
            "Human's 'quote'; DROP TABLE MemoryNode", "classified body SECRET123",
            epistemic_status="hypothesis",
            source="local://source", evidence_ref="source-card-42",
        )
        self.b = self.vault.add("Derived fact", "body SECRET456")
        self.vault.link(
            self.b["id"], self.a["id"], "derived_from",
            epistemic_status="inference",
            intent="test provenance", origin="review-r02",
            evidence_ref="run-431",
        )
        self.sidecar = InMemoryLadybugProjection(self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_initial_projection_idempotence_metadata_and_safe_binding(self):
        self.assertFalse(self.sidecar.status()["initialized"])
        one = self.sidecar.sync()
        self.assertTrue(one.refreshed)
        self.assertEqual(one.node_count, 2)
        self.assertEqual(one.edge_count, 1)
        self.assertFalse(self.sidecar.sync().refreshed)
        self.assertEqual(self.sidecar.status()["journal_digest"], one.journal_digest)
        edge = self.sidecar.neighbors(self.b["id"], direction="out")[0]
        self.assertEqual(edge["to"], self.a["id"])
        self.assertEqual(edge["epistemic_status"], "inference")
        self.assertEqual(edge["evidence_ref"], "run-431")
        self.assertFalse(edge["evidence_verified"])
        self.assertEqual(self.sidecar.neighbors(self.b["id"], direction="in"), [])
        self.assertEqual(self.sidecar.neighbors(self.a["id"], direction="in"),
                         self.sidecar.neighbors(self.b["id"], direction="out"))
        self.assertEqual(self.sidecar.neighbors(self.b["id"] + "' OR 1=1"),
                         [])
        with self.assertRaises(ProjectionError):
            self.sidecar.neighbors(self.a["id"], direction="all")
        # Only user-owned metadata appears in a memory-only derived database.
        self.assertFalse(any(self.root.glob("*.lbdb*")))

    def test_revise_staleness_unlink_archive_rebuild(self):
        first = self.sidecar.sync()
        self.vault.revise(self.a["id"], "updated source")
        changed = self.sidecar.sync()
        self.assertGreater(changed.journal_seq, first.journal_seq)
        self.assertNotEqual(changed.journal_digest, first.journal_digest)
        self.assertEqual(self.sidecar.neighbors(self.a["id"])[0]["relation"],
                         "derived_from")
        self.assertEqual(
            self.sidecar._conn.execute(
                "MATCH (m:MemoryNode) WHERE m.id = $id RETURN m.status",
                parameters={"id": self.b["id"]},
            ).get_all()[0][0], "stale"
        )
        self.vault.unlink(self.b["id"], self.a["id"], "derived_from")
        self.assertEqual(self.sidecar.sync().edge_count, 0)
        self.vault.archive(self.a["id"])
        after = self.sidecar.sync()
        self.assertEqual(after.node_count, 1)
        self.assertEqual(after.edge_count, 0)

    def test_transaction_rollback_and_subsequent_replay(self):
        original = self.sidecar.sync()
        self.vault.link(self.a["id"], self.b["id"], "supports")
        from noosphere_lite import ladybug_projection
        original_execute = ladybug_projection._execute
        def crash_on_edge(conn, statement, params=None):
            if statement == CREATE_EDGE:
                raise RuntimeError("simulated mid-transaction crash")
            return original_execute(conn, statement, params)
        with mock.patch.object(ladybug_projection, "_execute",
                               side_effect=crash_on_edge):
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                self.sidecar.sync()
        # Transaction rolls back *both* graph and receipt.
        self.assertEqual(self.sidecar.status()["journal_digest"],
                         original.journal_digest)
        self.assertEqual(len(self.sidecar.neighbors(self.a["id"])), 1)
        replayed = self.sidecar.sync()
        self.assertTrue(replayed.refreshed)
        self.assertEqual(replayed.edge_count, 2)
        self.assertNotEqual(replayed.journal_digest, original.journal_digest)

    def test_checkpoint_cannot_hide_missing_edges(self):
        before = self.sidecar.sync()
        self.assertEqual(before.edge_count, 1)
        self.sidecar._conn.execute(
            "MATCH (a:MemoryNode)-[e:MemoryEdge]->(b:MemoryNode) DELETE e"
        )
        self.assertEqual(self.sidecar._counts(), (2, 0))
        after = self.sidecar.sync()
        self.assertTrue(after.refreshed)
        self.assertEqual(after.journal_digest, before.journal_digest)
        self.assertEqual(self.sidecar._counts(), (2, 1))

    def test_explicit_mcp_tools_register_and_refresh_on_query(self):
        class StubApp:
            def __init__(self):
                self.registered = {}
            def tool(self):
                def register(fn):
                    self.registered[fn.__name__] = fn
                    return fn
                return register
        app = StubApp()
        register_mcp_tools(app, self.vault)
        self.assertEqual(set(app.registered), {
            "memory_ladybug_sync", "memory_ladybug_neighbors",
            "memory_ladybug_status",
        })
        self.assertFalse(app.registered["memory_ladybug_status"]()["initialized"])
        self.assertTrue(app.registered["memory_ladybug_sync"]()["refreshed"])
        out = app.registered["memory_ladybug_neighbors"](
            self.b["id"], direction="out",
        )
        self.assertEqual(len(out["edges"]), 1)
        self.assertFalse(out["claims_verified"])
        self.vault.unlink(self.b["id"], self.a["id"], "derived_from")
        refreshed = app.registered["memory_ladybug_neighbors"](self.a["id"])
        self.assertEqual(refreshed["edges"], [])

    def test_truncation_and_validation_fail_closed(self):
        self.sidecar.sync()
        good_status = self.sidecar.status()
        real_vault = self.sidecar.vault
        class Truncated:
            def graph_projection(self, **kwargs):
                record = real_vault.graph_projection(**kwargs)
                return {**record, "truncated": True}
        self.sidecar.vault = Truncated()
        with self.assertRaisesRegex(ProjectionError, "partial sync"):
            self.sidecar.sync()
        self.assertEqual(good_status, self.sidecar.status())
        with self.assertRaises(ProjectionError):
            InMemoryLadybugProjection(real_vault, limit=1001)


if __name__ == "__main__":
    unittest.main()
