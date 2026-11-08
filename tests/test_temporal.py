import csv
import tempfile
import unittest
from pathlib import Path
from noosphere_lite.vault import MemoryVault, VaultError
from noosphere_lite.interop import export_ladybug_csv, export_okf

class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        self.v = MemoryVault(self.root/"a", self.root/"b", self.root/"keys"/"key",
                             allow_same_device=True)
        self.v.initialize()
    def tearDown(self):
        self.t.cleanup()
    def test_as_of_historical_address(self):
        a = self.v.add("Address", "old", valid_from="2020-01-01T00:00:00+02:00",
                       valid_to="2022-01-01T00:00:00+02:00")
        b = self.v.add("Address", "new", valid_from="2022-01-01T00:00:00+02:00")
        self.v.add("Address", "unknown")
        self.assertEqual([x["id"] for x in self.v.search("Address", as_of="2021-06-01T00:00:00Z")], [a["id"]])
        self.assertEqual([x["id"] for x in self.v.search("Address", as_of="2024-06-01T00:00:00Z")], [b["id"]])
        self.assertEqual(len(self.v.search("Address")), 3)
        self.assertEqual(self.v.read(a["id"])["valid_from"], "2019-12-31T22:00:00+00:00")
        self.assertTrue(self.v.read(a["id"])["recorded_at"])
    def test_invalid_date(self):
        for value in ["2022-01-01", "bad", "2022-01-01T00:00:00"]:
            with self.assertRaises(VaultError):
                self.v.add("bad","date",valid_from=value)
        with self.assertRaises(VaultError):
            self.v.add("bad", "interval", valid_from="2024-01-01T00:00:00Z",
                       valid_to="2023-01-01T00:00:00Z")
    def test_timestamped_edges_and_revision(self):
        a = self.v.add("A","a",valid_from="2020-01-01T00:00:00Z")
        b = self.v.add("B","b")
        self.v.link(b["id"],a["id"],"derived_from")
        self.assertTrue(self.v.neighbors(a["id"])["links"][0]["recorded_at"])
        self.v.revise(a["id"],"new",valid_to="2021-01-01T00:00:00Z")
        self.assertEqual(self.v.read(b["id"])["status"],"stale")
        self.assertEqual(self.v.read(a["id"])["valid_to"],"2021-01-01T00:00:00+00:00")
    def test_explicit_exports(self):
        a=self.v.add("A","a")
        b=self.v.add("B","b")
        self.v.link(a["id"],b["id"])
        prev=(self.root/"a"/"journal.nlv").read_bytes()
        snap=self.v._snapshot()
        report=export_ladybug_csv(snap.nodes,snap.links,self.root/"csv")
        self.assertFalse(report["imported_into_ladybug"])
        with (self.root/"csv"/"edges.csv").open(encoding="utf-8") as f:
            self.assertEqual(len(list(csv.DictReader(f))),1)
        report=export_okf(snap.nodes,snap.links,self.root/"okf")
        self.assertEqual(report["edges"],1)
        self.assertIn("0.2",(self.root/"okf"/"index.md").read_text())
        self.assertEqual(prev,(self.root/"a"/"journal.nlv").read_bytes())
if __name__ == "__main__":
    unittest.main()
