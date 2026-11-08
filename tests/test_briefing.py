"""Regression tests: read-only encrypted briefings must not create plaintext data."""
import json
import tempfile
import unittest
from pathlib import Path

from noosphere_lite.briefing import MemoryBriefings
from noosphere_lite.evidence import EvidenceGate
from noosphere_lite.vault import MemoryVault, VaultError


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = MemoryVault(
            self.root/"a", self.root/"b", self.root/"keys"/"key",
            allow_same_device=True)
        self.vault.initialize()
        self.reader = MemoryBriefings(self.vault)
        self.gate = EvidenceGate(self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, kind, body="Text", title="Note", project="alpha",
            source="src/my_module.py", **kw):
        return self.vault.add(title, body, tags=["project:"+project],
                              kind=kind, source=source, **kw)["id"]

    def test_project_scope_exact_not_acls(self):
        self.add("negative","Never delete real customer data","Rule")
        self.add("invariant","Other team's credentials","Secret",project="beta")
        r=self.reader.briefing("alpha",include_evidence=False)
        self.assertEqual([x["text"] for x in r["records"]],
                         ["Never delete real customer data"])
        self.assertIn("not ACLs", r["warning"])

    def test_negative_invariant_before_open_loop_and_decision(self):
        a=self.add("decision","Choose R01")
        self.add("open_loop","Need tests")
        self.add("negative","Do not auto-delete")
        self.add("invariant","Keep trace")
        order=[v["kind"] for v in self.reader.briefing("alpha",include_evidence=False)["records"]]
        self.assertEqual(order,["negative","invariant","open_loop","decision"])
        self.assertNotIn(a, [v["id"] for v in self.reader.briefing("beta")["records"]])

    def test_stale_is_review_not_active(self):
        node=self.add("invariant","Keep integrity")
        child=self.add("decision","Follow source")
        self.vault.link(child,node,"derived_from")
        self.vault.invalidate(node,"test failure")
        r=self.reader.briefing("alpha",include_evidence=False)
        self.assertEqual(r["records"],[])
        self.assertEqual(len(r["review_required"]),2)
        self.assertTrue(all(x["reason"]=="stale" for x in r["review_required"]))

    def test_valid_times_and_missing_time_fail_closed(self):
        self.add("fact","Known 2022",
                 valid_from="2022-01-01T00:00:00Z",
                 valid_to="2023-01-01T00:00:00Z")
        self.add("fact","Not dated")
        r=self.reader.briefing("alpha",at="2022-06-01T00:00:00+00:00",
                                include_evidence=False)
        self.assertEqual([x["text"] for x in r["records"]],["Known 2022"])
        self.assertEqual(r["review_required"][0]["reason"],
                         "unknown_historical_validity")
        later=self.reader.briefing("alpha",at="2024-06-01T00:00:00Z",
                                    include_evidence=False)
        self.assertEqual(later["records"],[])
        self.assertEqual(later["counts"]["excluded_outside_validity"],1)

    def test_future_validity_not_active_now(self):
        self.add("negative","Future rule",valid_from="2099-01-01T00:00:00Z")
        r=self.reader.briefing("alpha",include_evidence=False)
        self.assertEqual(r["records"],[])
        self.assertEqual(r["counts"]["excluded_outside_validity"],1)

    def test_json_evidence_is_source_matched_not_truth(self):
        source=self.gate.add_source("observations",'{"count": 4}')["id"]
        self.gate.propose("test.count",source,"/count",scope="alpha")
        r=self.reader.briefing("alpha")
        self.assertEqual(r["source_matched_unreviewed"][0]["value"],4)
        self.assertEqual(r["evidence_state"],"source_matched_only")
        self.assertFalse(r["source_matched_unreviewed"][0]["truth_guaranteed"])
        self.assertEqual(r["records"],[])

    def test_evidence_conflicts_are_not_silently_chosen(self):
        src1=self.gate.add_source("a",'{"x": 1}')["id"]
        src2=self.gate.add_source("b",'{"x": 2}')["id"]
        self.gate.propose("item.x",src1,"/x",scope="alpha")
        self.gate.propose("item.x",src2,"/x",scope="alpha")
        r=self.reader.briefing("alpha")
        self.assertEqual(r["source_matched_unreviewed"],[])
        self.assertEqual(r["evidence_state"],"conflict")
        self.assertEqual(r["evidence_conflicts"],["item.x"])

    def test_rejected_evidence_is_excluded(self):
        src=self.gate.add_source("a",'{"x": 1}')["id"]
        claim=self.gate.propose("item.x",src,"/x",scope="alpha")
        self.gate.reject(claim["id"],"not trustworthy")
        r=self.reader.briefing("alpha")
        self.assertEqual(r["source_matched_unreviewed"],[])
        self.assertNotEqual(r["evidence_state"],"source_matched_only")

    def test_by_source_is_exact_and_stale_marked(self):
        path="src/a.py"
        first=self.add("invariant","Do not mutate ledger",source=path)
        self.add("decision","Different path",source="src/b.py")
        self.add("negative","Different project",project="beta",source=path)
        r=self.reader.by_source("alpha",path)
        self.assertEqual([x["id"] for x in r["records"]],[first])
        self.assertFalse(r["source_verified"])
        self.vault.invalidate(first,"source changed")
        stale=self.reader.by_source("alpha",path)["records"]
        self.assertTrue(stale[0]["needs_review"])
        self.assertEqual(self.reader.by_source("alpha","SRC/A.PY")["records"],[])

    def test_unavailable_path_is_never_opened(self):
        before=list(self.root.rglob("*"))
        self.add("decision","Exact label only",source="/no/such/file/private.py")
        r=self.reader.by_source("alpha","/no/such/file/private.py")
        self.assertEqual(r["matched"],1)
        self.assertFalse(r["source_verified"])
        self.assertEqual(before,list(self.root.rglob("*"))[:len(before)])

    def test_large_record_is_skipped_not_misleadingly_truncated(self):
        self.add("negative","X"*6000)
        r=self.reader.briefing("alpha",max_chars=1500,include_evidence=False)
        self.assertEqual(r["records"],[])
        self.assertEqual(r["counts"]["record_omitted"],1)
        self.assertTrue(r["truncated"])
        self.assertLess(len(json.dumps(r)),2200)

    def test_evidence_not_cross_scoped(self):
        source=self.gate.add_source("audit",'{"v":true}')["id"]
        self.gate.propose("x",source,"/v",scope="beta")
        r=self.reader.briefing("alpha")
        self.assertEqual(r["source_matched_unreviewed"],[])

    def test_regular_note_and_internal_evidence_do_not_bypass(self):
        self.vault.add("casual","Unverified",tags=["project:alpha"],kind="note")
        self.vault.add("not really","{}",tags=["project:alpha"],kind="evidence_claim")
        self.assertEqual(self.reader.briefing("alpha",include_evidence=False)["records"],[])

    def test_bad_inputs_fail(self):
        for project in ("", "project/../../etc", "X"*49, "alpha x"):
            with self.assertRaises(VaultError):
                self.reader.briefing(project)
        for bad in ("", "\x00file"):
            with self.assertRaises(VaultError):
                self.reader.by_source("alpha",bad)
        with self.assertRaises(VaultError):
            self.reader.briefing("alpha",limit=True)
        with self.assertRaises(VaultError):
            self.reader.briefing("alpha",max_chars=999)
        with self.assertRaises(VaultError):
            self.reader.briefing("alpha",at="2026-01-01")

    def test_mirror_replay_after_multiple_queries(self):
        self.add("invariant","Critical")
        a=self.reader.briefing("alpha")["records"]
        b=MemoryBriefings(self.vault).briefing("alpha")["records"]
        self.assertEqual(a,b)
        self.assertEqual(self.vault.status()["events"],1)
        self.assertTrue(self.vault.status()["mirrors_valid"])

if __name__ == "__main__":
    unittest.main()
