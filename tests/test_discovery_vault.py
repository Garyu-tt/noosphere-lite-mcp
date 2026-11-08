"""Noosphere Lite integration safety regression for experimental link discovery."""
import tempfile
import unittest
from pathlib import Path

from noosphere_lite.vault import MemoryVault, VaultError


class DiscoveryVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.vault=MemoryVault(root/"one",root/"two",root/"keys"/"secret",allow_same_device=True)
        self.vault.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def _pair(self):
        a=self.vault.add("Progress-aware watchdog robot","Adaptive deadline and worker heartbeat progress",["watchdog","progress"],"experiment")
        b=self.vault.add("Progress-aware watchdog subprocess","Adaptive deadline based on process heartbeat progress",["watchdog","progress"],"experiment")
        return a,b

    def test_real_encrypted_vault_suggests_without_writing(self):
        a,b=self._pair()
        before=self.vault.status()["events"]
        encrypted_before=(self.vault.primary/"journal.nlv").read_bytes()
        out=self.vault.suggest_links(a["id"],limit=7)
        self.assertIn(b["id"],[x["id"] for x in out])
        self.assertTrue(all(x["discovery_status"]=="unverified_candidate" for x in out))
        self.assertEqual(before,self.vault.status()["events"])
        self.assertEqual(encrypted_before,(self.vault.primary/"journal.nlv").read_bytes())

    def test_explicit_relation_excludes_candidate(self):
        a,b=self._pair()
        self.vault.link(a["id"],b["id"],"related")
        self.assertEqual(self.vault.suggest_links(a["id"]),[])

    def test_archived_neighbor_excluded(self):
        a,b=self._pair()
        self.vault.archive(b["id"])
        self.assertEqual(self.vault.suggest_links(a["id"]),[])

    def test_unknown_node_is_vault_error(self):
        with self.assertRaises(VaultError):
            self.vault.suggest_links("missing")


if __name__=="__main__":
    unittest.main()
