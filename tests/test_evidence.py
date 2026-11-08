import json
import tempfile
import unittest
from pathlib import Path

from noosphere_lite.evidence import EvidenceGate
from noosphere_lite.vault import MemoryVault, VaultError


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.vault = MemoryVault(root / "a", root / "b", root / "key" / "key",
                                 allow_same_device=True)
        self.vault.initialize()
        self.gate = EvidenceGate(self.vault)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, text='{"address":"old", "count": 7}'):
        return self.gate.add_source("audit", text)["id"]

    def test_source_pointer_verification(self):
        source = self.source()
        self.gate.propose("user.address", source, "/address")
        r = self.gate.query("user.address")
        self.assertEqual(r["facts"][0]["value"], "old")
        self.assertFalse(r["facts"][0]["truth_guaranteed"])
        self.assertEqual(r["facts"][0]["pointer"], "/address")

    def test_rejected_fact_never_resurrects(self):
        source = self.source()
        claim = self.gate.propose("user.address", source, "/address")
        self.gate.reject(claim["id"], "outdated")
        self.assertFalse(self.gate.query("user.address")["facts"])
        with self.assertRaisesRegex(VaultError, "reintroduced"):
            self.gate.propose("user.address", source, "/address")
        # New values are not forbidden by tombstone for the old value.
        other = self.source('{"address":"new"}')
        self.gate.propose("user.address", other, "/address")
        self.assertEqual(self.gate.query("user.address")["facts"][0]["value"], "new")

    def test_conflict_fails_closed(self):
        a = self.source('{"v":1}')
        b = self.source('{"v":2}')
        self.gate.propose("fact.x", a, "/v")
        self.gate.propose("fact.x", b, "/v")
        result = self.gate.query("fact.x")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["conflicts"], ["fact.x"])
        self.assertEqual(result["facts"], [])

    def test_source_revised_or_invalidated_drops_claim(self):
        source = self.source()
        claim = self.gate.propose("fact.x", source, "/count")
        self.vault.revise(source, '{"address":"new","count":7}')
        self.assertEqual(self.gate.query("fact.x")["facts"], [])
        self.assertEqual(self.vault.read(claim["id"])["status"], "stale")

    def test_scope_isolation_not_acl(self):
        src = self.source()
        self.gate.propose("test", src, "/count", scope="projectA")
        self.assertEqual(self.gate.query("test", scope="default")["facts"], [])
        self.assertEqual(len(self.gate.query("test", scope="projectA")["facts"]), 1)

    def test_temporal_windows_and_unknown(self):
        source = self.source()
        self.gate.propose("historic.address", source, "/address",
                          valid_from="2020-01-01T00:00:00Z",
                          valid_to="2022-01-01T00:00:00Z")
        self.assertEqual(self.gate.query("historic.address", as_of="2021-05-01T00:00:00Z")["facts"][0]["value"], "old")
        self.assertEqual(self.gate.query("historic.address", as_of="2024-01-01T00:00:00Z")["facts"], [])
        self.gate.propose("historic.unknown", source, "/address")
        self.assertEqual(self.gate.query("historic.unknown", as_of="2021-05-01T00:00:00Z")["facts"], [])

    def test_expired_evidence(self):
        source = self.source()
        self.gate.propose("expired", source, "/count", stale_after="2025-01-01T00:00:00Z")
        self.assertEqual(self.gate.query("expired")["facts"], [])

    def test_unicode_and_escaped_pointer(self):
        source = self.source('{"знання": {"адрес/а": "Київ"}}')
        self.gate.propose("ukraine.address", source, "/знання/адрес~1а")
        self.assertEqual(self.gate.query("Київ")["facts"][0]["value"], "Київ")

    def test_invalid_pointer_fails(self):
        source = self.source()
        for pointer in ("not/a/pointer", "/other", "/~2"):
            with self.assertRaises(VaultError):
                self.gate.propose("bad", source, pointer)

    def test_source_not_trusted_for_arbitrary_claim_semantics(self):
        source = self.source()
        result = self.gate.propose("arbitrary.name", source, "/count")
        self.assertEqual(result["status"], "source_matched_unreviewed")
        self.assertFalse(self.gate.query("arbitrary.name")["facts"][0]["truth_guaranteed"])

    def test_vault_general_context_does_not_index_evidence(self):
        source = self.source()
        self.gate.propose("fact.example", source, "/address")
        self.assertEqual(self.vault.search("fact.example"), [])

    def test_immutable_retractions_and_claims(self):
        source = self.source()
        claim = self.gate.propose("immutable", source, "/count")
        with self.assertRaisesRegex(VaultError, "immutable"):
            self.vault.revise(claim["id"], "{}")
        tomb = self.gate.reject(claim["id"], "false")
        with self.assertRaisesRegex(VaultError, "immutable"):
            self.vault.revise(tomb["tombstone_id"], "{}")
        with self.assertRaisesRegex(VaultError, "cannot be archived"):
            self.vault.archive(tomb["tombstone_id"])

    def test_no_bypass_with_unlinked_forged_claim(self):
        source = self.source()
        real = self.gate.propose("linked", source, "/count")
        node = self.vault.read(real["id"])
        # Same signed-looking metadata, but no source dependency link.
        with self.assertRaisesRegex(VaultError, "reserved"):
            self.vault.add("linked", node["body"], kind="evidence_claim")
        hits = self.gate.query("linked")["facts"]
        self.assertEqual([x["claim_id"] for x in hits], [real["id"]])

    def test_stale_source_rejected_without_cascade(self):
        source = self.source()
        claim = self.gate.propose("source", source, "/count")
        self.vault.unlink(claim["id"], source, "derived_from")
        self.vault.invalidate(source, "revoked")
        self.assertEqual(self.gate.query("source")["facts"], [])

    def test_journal_replay_and_mirror(self):
        source = self.source()
        self.gate.propose("replay", source, "/count")
        self.assertEqual(self.gate.query("replay")["facts"][0]["value"], 7)
        self.assertTrue(self.vault.status()["mirrors_valid"])


if __name__ == "__main__":
    unittest.main()
