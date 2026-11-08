"""Reference implementation tests: synthetic jobs; never touch live Noosphere."""
import tempfile
import unittest
from pathlib import Path

from examples.reviewed_plasticity.engine import (
    Edge, ReviewedLearner, confidence_from_status, effective_weight,
)

class ReviewedLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.artifacts = root / "artifacts"
        self.artifacts.mkdir()
        self.proof = self.artifacts / "test.json"
        self.proof.write_text('{"unit_test":true,"result":"pass"}')
        self.database_dir = root / "private"
        self.database_dir.mkdir(mode=0o700)
        self.edge = Edge("memory:a", "memory:b", "supports")
        self.other = Edge("memory:a", "memory:c", "blocks")
        self.known = {self.edge, self.other}
        self.store = ReviewedLearner(
            self.database_dir / "weights.sqlite3", self.artifacts,
            {"qa-reviewer"}, lambda e: e in self.known,
        )

    def start(self, job="job-1"):
        self.store.begin_job(job, "requester", "executor")

    def submitted(self, job="job-1", edge=None):
        self.start(job)
        return self.store.declare(job, "executor", edge or self.edge, "test.json")

    def reviewed(self, job="job-1", edge=None, ok=True):
        usage = self.submitted(job, edge)
        n = self.store.review(job, "qa-reviewer", ok, [usage],
                              "Independently reproduced the linked result.")
        self.assertEqual(n, 1)
        return usage

    def test_verified_feedback_improves_weight(self):
        baseline = self.store.weight(self.edge)
        self.reviewed()
        self.assertEqual(self.store.cycle()["applied"], 1)
        self.assertGreater(self.store.weight(self.edge), baseline)
        self.assertEqual(self.store.status()["learned_edges"], 1)

    def test_failed_feedback_reduces_utility_and_weight(self):
        base = self.store.weight(self.edge)
        self.reviewed(ok=False)
        self.assertEqual(self.store.cycle()["applied"], 1)
        self.assertLess(self.store.weight(self.edge), base)

    def test_no_learning_from_unreviewed_work(self):
        self.submitted()
        self.assertEqual(self.store.cycle()["applied"], 0)
        self.assertEqual(self.store.status()["learning_events"], 0)

    def test_self_review_denied(self):
        usage = self.submitted()
        for who in ("requester", "executor", "random-agent"):
            with self.assertRaisesRegex(ValueError, "separate authorized"):
                self.store.review("job-1", who, True, [usage],
                                  "I checked everything by myself.")
        self.assertEqual(self.store.cycle()["applied"], 0)

    def test_unknown_edge_denied(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "authoritative"):
            self.store.declare("job-1", "executor",
                               Edge("invented", "invented", "related"), "test.json")

    def test_wrong_actor_denied(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "assigned worker"):
            self.store.declare("job-1", "requester", self.edge, "test.json")

    def test_evidence_tampering_before_review_denied(self):
        usage = self.submitted()
        self.proof.write_text('{"tampered":true}')
        with self.assertRaisesRegex(ValueError, "digest changed"):
            self.store.review("job-1", "qa-reviewer", True, [usage],
                              "Independently checked exact file hash.")

    def test_evidence_tampering_after_review_skips(self):
        self.reviewed()
        self.proof.write_text('{"tampered":true}')
        self.assertEqual(self.store.cycle()["skipped_evidence"], 1)
        self.assertEqual(self.store.status()["learned_edges"], 0)

    def test_cannot_launder_proof_symlink(self):
        self.start()
        (self.artifacts / "link.json").symlink_to(self.proof)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.store.declare("job-1", "executor", self.edge, "link.json")

    def test_cross_job_attribution_denied(self):
        a = self.submitted("one")
        self.start("two")
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.store.review("two", "qa-reviewer", True, [a],
                              "I verified the unrelated record.")

    def test_at_most_four_usages_and_no_duplicate(self):
        self.start()
        self.store.declare("job-1", "executor", self.edge, "test.json")
        with self.assertRaises(Exception):
            self.store.declare("job-1", "executor", self.edge, "test.json")

    def test_idempotent_scheduler_and_rollback(self):
        usage = self.reviewed()
        self.assertEqual(self.store.cycle()["applied"], 1)
        self.assertEqual(self.store.cycle()["applied"], 0)
        self.store.rollback(usage)
        self.assertEqual(self.store.cycle()["applied"], 0)
        self.assertEqual(self.store.status()["learning_events"], 0)
        self.assertEqual(self.store.status()["learned_edges"], 0)

    def test_rollback_must_be_latest_for_edge(self):
        first = self.reviewed("one")
        self.store.cycle()
        self.reviewed("two")
        self.store.cycle()
        with self.assertRaisesRegex(ValueError, "latest first"):
            self.store.rollback(first)
        self.store.rollback(2)
        self.store.rollback(first)
        self.assertEqual(self.store.status()["learned_edges"], 0)

    def test_status_confidence_not_trained_by_reward(self):
        self.reviewed()
        self.store.cycle()
        low = self.store.weight(self.edge, source_status="lexical_unverified")
        high = self.store.weight(self.edge, source_status="source_observation")
        self.assertLess(low, high)
        self.assertEqual(confidence_from_status("lexical_unverified"), 0.15)
        self.assertEqual(confidence_from_status("source_observation"), 0.55)

    def test_no_plaintext_evidence_in_sidecar(self):
        self.reviewed()
        self.store.cycle()
        data = (self.database_dir / "weights.sqlite3").read_bytes()
        self.assertNotIn(self.proof.read_bytes(), data)

    def test_job_can_be_reviewed_without_learning(self):
        self.start()
        self.assertEqual(
            self.store.review("job-1", "qa-reviewer", True, [],
                              "An independent verdict, no attributed edges."),
            0)
        self.assertEqual(self.store.cycle()["applied"], 0)

    def test_numeric_bounds(self):
        for n in range(16):
            self.reviewed(str(n))
        self.assertEqual(self.store.cycle()["applied"], 16)
        self.assertLessEqual(self.store.weight(self.edge), 10.0)
        self.assertGreaterEqual(self.store.weight(self.edge), 0.0)
        with self.assertRaises(ValueError):
            effective_weight(float("nan"), 0.5, 0.0, "source_observation")

if __name__ == "__main__":
    unittest.main()
