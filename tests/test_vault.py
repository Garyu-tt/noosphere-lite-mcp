import tempfile
import unittest
from pathlib import Path
from noosphere_lite.vault import MemoryVault, VaultError

class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.primary = root / "disk1"
        self.mirror = root / "disk2"
        self.key = root / "config" / "key"
        self.vault = MemoryVault(self.primary, self.mirror, self.key, allow_same_device=True)
        self.vault.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_encrypted_write_search_read_context_and_links(self):
        a = self.vault.add("Build plan", "Install a local MCP memory service", ["planning", "linux"], "decision")
        b = self.vault.add("Validation", "Check encrypted mirror checksums", ["security"], "task")
        self.assertIn(a["id"], [x["id"] for x in self.vault.search("linux")])
        self.assertIn("MCP", self.vault.read(a["id"])["body"])
        self.assertEqual(len(self.vault.context("MCP")["memories"]), 1)
        self.vault.link(a["id"], b["id"], "blocks")
        near = self.vault.neighbors(a["id"])
        self.assertEqual(len(near["nodes"]), 2)
        self.assertEqual(near["links"][0]["relation"], "blocks")
        self.vault.unlink(a["id"], b["id"], "blocks")
        self.assertEqual(self.vault.neighbors(a["id"])["links"], [])
        self.assertNotIn(b"Install a local MCP memory service", (self.primary / "journal.nlv").read_bytes())
        self.assertEqual((self.primary / "journal.nlv").read_bytes(), (self.mirror / "journal.nlv").read_bytes())

    def test_recovery_from_corrupt_replica(self):
        a = self.vault.add("Restore me", "Durable private payload")
        (self.primary / "journal.nlv").write_bytes(b"corrupt")
        self.assertEqual(self.vault.read(a["id"])["title"], "Restore me")
        self.assertEqual((self.primary / "journal.nlv").read_bytes(), (self.mirror / "journal.nlv").read_bytes())

    def test_tampering_both_replicas_is_rejected(self):
        self.vault.add("Secret", "Never plaintext")
        for root in (self.primary, self.mirror):
            p = root / "journal.nlv"
            raw = bytearray(p.read_bytes())
            raw[-2] ^= 0x40
            p.write_bytes(raw)
        with self.assertRaises(VaultError):
            self.vault.status()

    def test_key_mismatch_rejected(self):
        self.vault.add("Secret", "Protected content")
        self.key.write_bytes(b"a"*32)
        with self.assertRaises(VaultError):
            self.vault.status()

    def test_archiving_does_not_promise_cryptographic_erasure(self):
        a = self.vault.add("Old memory", "Will remain in encrypted log")
        result = self.vault.archive(a["id"])
        self.assertIn("history", result["warning"])
        self.assertEqual(self.vault.search("Old memory"), [])
        with self.assertRaises(VaultError):
            self.vault.read(a["id"])

    def test_requires_independent_devices_by_default(self):
        strict = MemoryVault(self.primary, self.mirror, self.key)
        with self.assertRaises(VaultError):
            strict.status()

    def test_no_overwrite_existing_journals(self):
        with self.assertRaises(VaultError):
            self.vault.initialize()

if __name__ == "__main__":
    unittest.main()

