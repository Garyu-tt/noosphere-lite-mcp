"""R03 graph-scale and bounded traversal regression suite.

Synthetic snapshots exercise >1000 entities without writing decrypted test
corpus content to disk. Base journal encryption/replay has separate tests.
"""
from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from noosphere_lite.graph_plan import GraphPlanError, plan_graph
from noosphere_lite.knowledge_evolution import project_snapshot
from noosphere_lite.vault import MemoryVault, Snapshot
from noosphere_lite.ladybug_projection import (
    InMemoryLadybugProjection, ProjectionError, CREATE_NODE,
)


def synthetic_snapshot(size: int, *, edges: bool = True) -> Snapshot:
    nodes = {}
    links = {}
    for i in range(size):
        key = f"node-{i:05d}"
        nodes[key] = {
            "id": key, "title": f"Node {i:05d}",
            "kind": "observation", "body": f"DO NOT EXPORT BODY {i}",
            "source": "local://fixture", "created": "2026-11-09T00:00:00+00:00",
            "epistemic_status": "unreviewed", "status": "current",
        }
        if edges and i:
            previous = f"node-{i-1:05d}"
            links[(previous, key, "depends_on")] = "2026-11-09T00:00:00+00:00"
    digest = hashlib.sha256(f"fixture:{size}:{edges}".encode()).digest()
    return Snapshot(nodes, links, [], digest, 3 * size)


class GraphPlanTests(unittest.TestCase):
    def test_streamed_projection_hash_matches_legacy_canonical_hash(self):
        snap = synthetic_snapshot(12)
        plan = plan_graph(snap)
        legacy = project_snapshot(snap, limit=12)
        self.assertEqual(plan.projection_hash, legacy["projection_hash"])
        self.assertEqual(plan.node_count, len(legacy["nodes"]))
        self.assertEqual(plan.edge_count, len(legacy["links"]))
        self.assertEqual(sum(map(len, plan.node_batches(5))), 12)
        self.assertEqual(sum(map(len, plan.edge_batches(5))), 11)
        self.assertTrue(all("body" not in n for b in plan.node_batches(5) for n in b))
        self.assertEqual(plan.journal_seq, snap.seq)

    def test_full_plan_exceeds_previous_one_thousand_limit(self):
        snap = synthetic_snapshot(1205)
        plan = plan_graph(snap, max_nodes=1500)
        self.assertEqual(plan.node_count, 1205)
        self.assertEqual(plan.edge_count, 1204)
        self.assertEqual(sum(map(len, plan.node_batches(256))), 1205)
        with self.assertRaisesRegex(GraphPlanError, "max_nodes"):
            plan_graph(snap, max_nodes=1000)
        with self.assertRaisesRegex(GraphPlanError, "max_edges"):
            plan_graph(snap, max_edges=500)
        with self.assertRaises(GraphPlanError):
            plan_graph(snap, max_nodes=True)
        with self.assertRaises(GraphPlanError):
            list(plan.node_batches(batch_size=1001))


@unittest.skipUnless(importlib.util.find_spec("ladybug") is not None,
                     "optional LadybugDB not installed")
class LadybugScaleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = MemoryVault(
            root / "a", root / "b", root / "config" / "key",
            allow_same_device=True,
        )
        self.vault.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_bulk_materialization_over_1000_no_truncation(self):
        self.vault._snapshot = lambda: synthetic_snapshot(1205)
        sidecar = InMemoryLadybugProjection(self.vault, batch_size=128)
        state = sidecar.sync()
        self.assertEqual((state.node_count, state.edge_count), (1205, 1204))
        self.assertEqual(sidecar._counts(), (1205, 1204))
        self.assertFalse(sidecar.sync().refreshed)
        self.assertEqual(
            sidecar.neighbors("node-00600", direction="out")[0]["to"],
            "node-00601",
        )
        self.assertEqual(
            sidecar.paths("node-00600", direction="out", depth=4)["nodes"][-1]["id"],
            "node-00604",
        )
        self.assertEqual(sidecar.status()["projection_hash"], state.projection_hash)

    def test_second_batch_failure_rolls_back_whole_graph(self):
        real = self.vault.add("Real observation", "secrets stay encrypted")
        sidecar = InMemoryLadybugProjection(self.vault, batch_size=50)
        previous = sidecar.sync()
        self.vault._snapshot = lambda: synthetic_snapshot(151)
        from noosphere_lite import ladybug_projection
        execute = ladybug_projection._execute
        seen = {"batches": 0}
        def fail_second_batch(connection, query, params=None):
            if query == CREATE_NODE:
                seen["batches"] += 1
                if seen["batches"] == 2:
                    raise RuntimeError("injected failure")
            return execute(connection, query, params)
        with patch.object(ladybug_projection, "_execute", side_effect=fail_second_batch):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                sidecar.sync()
        self.assertEqual(sidecar.status()["journal_digest"], previous.journal_digest)
        self.assertEqual(sidecar._counts(), (1, 0))
        self.assertFalse(sidecar.neighbors(real["id"]))
        self.assertEqual(sidecar.sync().node_count, 151)

    def test_multihop_cycles_direction_filter_and_bounds(self):
        a, b, c, d, e = [self.vault.add(letter, letter)["id"] for letter in "ABCDE"]
        self.vault.link(a, b, "supports")
        self.vault.link(b, c, "supports")
        self.vault.link(c, a, "supports")
        self.vault.link(c, d, "contradicts")
        self.vault.link(e, a, "derived_from")
        sidecar = InMemoryLadybugProjection(self.vault)
        sidecar.sync()
        outgoing = sidecar.paths(a, depth=3, direction="out")
        self.assertEqual({n["id"] for n in outgoing["nodes"]}, {a,b,c,d})
        self.assertEqual(len(outgoing["links"]), 4)
        self.assertTrue(all(not x["evidence_verified"] for x in outgoing["links"]))
        incoming = sidecar.paths(a, depth=1, direction="in")
        self.assertEqual({n["id"] for n in incoming["nodes"]}, {a,c,e})
        support = sidecar.paths(a, depth=4, direction="out", relation="supports")
        self.assertNotIn(d, {n["id"] for n in support["nodes"]})
        self.assertFalse(support["truncated"])
        constrained = sidecar.paths(a, depth=4, direction="out", max_nodes=2)
        self.assertTrue(constrained["truncated"])
        self.assertLessEqual(len(constrained["nodes"]), 2)
        limited_edges = sidecar.paths(a, depth=4, direction="out", max_edges=1)
        self.assertTrue(limited_edges["truncated"])
        self.assertEqual(len(limited_edges["links"]), 1)
        injection = sidecar.paths(a, depth=4, relation="supports' OR 1=1")
        self.assertEqual(len(injection["links"]), 0)
        for invalid in (0, 5, True):
            with self.assertRaises(ProjectionError):
                sidecar.paths(a, depth=invalid)
        with self.assertRaisesRegex(ProjectionError, "missing"):
            sidecar.paths("missing")

    def test_threaded_checkpoint_and_traversals_share_one_connection_safely(self):
        self.vault._snapshot = lambda: synthetic_snapshot(40)
        sidecar = InMemoryLadybugProjection(self.vault, batch_size=10)
        sidecar.sync()
        def run_one(i):
            if i % 2:
                return sidecar.paths("node-00020", depth=2, direction="both")
            return sidecar.sync()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run_one, range(24)))
        self.assertEqual(sidecar._counts(), (40, 39))
        self.assertTrue(all(
            obj["origin"] == "node-00020" for obj in results
            if isinstance(obj, dict)
        ))

    def test_one_source_snapshot_per_refresh(self):
        one = synthetic_snapshot(3)
        two = synthetic_snapshot(4)
        calls = []
        def alternate():
            calls.append(True)
            return one if len(calls) == 1 else two
        self.vault._snapshot = alternate
        sidecar = InMemoryLadybugProjection(self.vault)
        first = sidecar.sync()
        self.assertEqual((len(calls), first.node_count), (1, 3))
        second = sidecar.sync()
        self.assertEqual((len(calls), second.node_count), (2, 4))
        self.assertEqual(sidecar._counts(), (4, 3))

    def test_never_conflate_authoritative_and_projected_status(self):
        snap = synthetic_snapshot(1001)
        self.vault._snapshot = lambda: snap
        sidecar = InMemoryLadybugProjection(self.vault, limit=1000)
        with self.assertRaisesRegex(ProjectionError, "max_nodes"):
            sidecar.sync()
        self.assertFalse(sidecar.status()["initialized"])


if __name__ == "__main__":
    unittest.main()
