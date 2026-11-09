import hashlib
import tempfile
import unittest
from pathlib import Path

from noosphere_lite.knowledge_evolution import (
    markdown_hashes, merge_markdown_enrichment, project_snapshot,
)
from noosphere_lite.vault import MemoryVault, VaultError


class KnowledgeEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = MemoryVault(root / "a", root / "b", root / "config" / "key",
                                 allow_same_device=True)
        self.vault.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_owned_markdown_does_not_self_trigger(self):
        original = "# Human claim\n\n## End Index Hash\n## AI Enrichment\nold\n"
        old = markdown_hashes(original)
        revised = merge_markdown_enrichment(
            original, "machine observation", old["author_hash"],
        )
        new = markdown_hashes(revised)
        self.assertEqual(old["author_hash"], new["author_hash"])
        self.assertNotEqual(old["machine_hash"], new["machine_hash"])
        self.assertNotEqual(old["file_hash"], new["file_hash"])
        with self.assertRaisesRegex(ValueError, "self-enrichment"):
            merge_markdown_enrichment(revised, "again", new["author_hash"],
                                      last_enriched_author_hash=old["author_hash"])

    def test_owned_markdown_rejects_misplaced_sentinel_and_race(self):
        with self.assertRaises(ValueError):
            markdown_hashes("No sentinel")
        with self.assertRaises(ValueError):
            markdown_hashes("first\n## End Index Hash\nx\n## End Index Hash\ny")
        doc = "A\n## End Index Hash\n## AI Enrichment\n"
        expected = markdown_hashes(doc)["author_hash"]
        with self.assertRaisesRegex(ValueError, "changed"):
            merge_markdown_enrichment("B\n## End Index Hash\n", "text", expected)

    def test_machine_only_journal_event_and_replay(self):
        item = self.vault.add("Proof", "author v1", kind="hypothesis")
        gate = self.vault.enrichment_gate(item["id"])
        self.assertTrue(gate["needs_enrichment"])
        result = self.vault.enrich(item["id"], "Evidence to investigate",
                                   gate["author_hash"])
        self.assertTrue(result["enriched"])
        self.assertFalse(self.vault.enrichment_gate(item["id"])["needs_enrichment"])
        read = self.vault.read(item["id"])
        self.assertEqual(read["body"], "author v1")
        self.assertEqual(read["machine_enrichment"], "Evidence to investigate")
        self.assertFalse(read["enrichment_stale"])
        self.assertEqual(self.vault.status()["events"], 2)
        with self.assertRaisesRegex(VaultError, "unchanged"):
            self.vault.enrich(item["id"], "no loop", gate["author_hash"])
        self.assertEqual(self.vault.status()["events"], 2)
        reloaded = MemoryVault(self.vault.primary, self.vault.mirror,
                               self.vault.key_file, allow_same_device=True)
        self.assertEqual(reloaded.read(item["id"])["machine_enrichment"],
                         "Evidence to investigate")

    def test_author_revision_stales_only_enrichment_until_re_enriched(self):
        item = self.vault.add("Observation", "v1")
        first = self.vault.enrichment_gate(item["id"])["author_hash"]
        self.vault.enrich(item["id"], "computed on v1", first)
        self.vault.revise(item["id"], "v2")
        self.assertTrue(self.vault.read(item["id"])["enrichment_stale"])
        fresh = self.vault.enrichment_gate(item["id"])
        self.assertTrue(fresh["needs_enrichment"])
        with self.assertRaisesRegex(VaultError, "changed"):
            self.vault.enrich(item["id"], "old result", first)
        self.vault.enrich(item["id"], "computed on v2", fresh["author_hash"])
        self.assertFalse(self.vault.read(item["id"])["enrichment_stale"])

    def test_epistemic_qualifiers_are_not_evidence(self):
        item = self.vault.add("Claim", "Untested", source="https://example.test/x",
                              epistemic_status="hypothesis",
                              intent="consider later", evidence_ref="test-23")
        node = self.vault.read(item["id"])
        self.assertEqual(node["epistemic_status"], "hypothesis")
        self.assertEqual(node["evidence_ref"], "test-23")
        p = self.vault.graph_projection()
        self.assertFalse(p["nodes"][0]["evidence_verified"])
        with self.assertRaises(VaultError):
            self.vault.add("Invalid", "body", epistemic_status="certified")

    def test_projection_deterministic_bounded_and_no_plaintext_output(self):
        x = self.vault.add("One", "private body: SECRET123")
        y = self.vault.add("Two", "private body: SECRET456")
        self.vault.link(y["id"], x["id"], "derived_from")
        p = self.vault.graph_projection()
        self.assertEqual(len(p["nodes"]), 2)
        self.assertEqual(len(p["links"]), 1)
        self.assertFalse(p["truncated"])
        self.assertFalse(p["projection_is_authoritative"])
        self.assertNotIn("SECRET", str(p))
        self.assertEqual(p["links"][0]["relation"], "derived_from")
        self.assertEqual(p["projection_hash"],
                         self.vault.graph_projection()["projection_hash"])
        self.assertEqual(p["journal_seq"], 3)
        self.assertEqual(p["journal_digest"],
                         self.vault._snapshot().digest.hex())
        one = self.vault.graph_projection(limit=1)
        self.assertEqual(len(one["nodes"]), 1)
        self.assertEqual(len(one["links"]), 0)
        self.assertTrue(one["truncated"])
        with self.assertRaises(ValueError):
            self.vault.graph_projection(limit=1001)

    def test_link_qualifiers_replay_without_promoting_evidence(self):
        a = self.vault.add("Implementation", "actual code")
        b = self.vault.add("Requirement", "requirement text")
        self.vault.link(
            a["id"], b["id"], "implements", epistemic_status="inference",
            evidence_ref="https://example.test/test-report",
            intent="trace the requirement", origin="reviewer-r01",
        )
        link = self.vault.graph_projection()["links"][0]
        self.assertEqual(link["qualifiers"]["intent"], "trace the requirement")
        self.assertEqual(link["qualifiers"]["epistemic_status"], "inference")
        self.assertFalse(link["evidence_verified"])
        reread = MemoryVault(self.vault.primary, self.vault.mirror,
                             self.vault.key_file, allow_same_device=True)
        self.assertEqual(
            reread.neighbors(a["id"])["links"][0]["qualifiers"]["origin"],
            "reviewer-r01",
        )
        self.vault.unlink(a["id"], b["id"], "implements")
        self.assertEqual(self.vault.graph_projection()["links"], [])

    def test_enrichment_is_never_written_in_plaintext_cache(self):
        item = self.vault.add("Human", "plaintext secret author")
        token = self.vault.enrichment_gate(item["id"])["author_hash"]
        self.vault.enrich(item["id"], "plaintext secret enrichment", token)
        for storage in (self.vault.primary, self.vault.mirror):
            blob = (storage / "journal.nlv").read_bytes()
            self.assertNotIn(b"plaintext secret author", blob)
            self.assertNotIn(b"plaintext secret enrichment", blob)


if __name__ == "__main__":
    unittest.main()
