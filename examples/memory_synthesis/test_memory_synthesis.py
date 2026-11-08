# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable tests for the optional memory synthesis sidecar."""
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from memory_synthesis import (
    add,brief,connect,corroborate,feedback,forget,recall,resolve,
    source_status,timestamp,validate_ledger,
)

class MemorySynthesisTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "evidence.txt"
        self.path.write_text("Lives in Lisbon. Later lives in Pune. Do not deploy to prod.",
                             encoding="utf-8")
        self.db = connect(Path(self.folder.name) / "memory.sqlite3")

    def tearDown(self):
        self.db.close()
        self.folder.cleanup()

    def put(self, **kwargs):
        return add(self.db,"demo","alice","residence","fact",
                   kwargs.pop("text","Lives in Lisbon."),str(self.path),**kwargs)

    def test_verified_quote_and_forgery(self):
        rid=self.put(trust="verbatim",quote="Lives in Lisbon.")
        self.assertEqual(recall(self.db,"Lisbon")[0]["id"],rid)
        with self.assertRaisesRegex(ValueError,"verbatim"):
            self.put(text="Lives on Mars.",trust="verbatim",quote="Lives on Mars.")

    def test_explicit_history(self):
        old=self.put(valid_from="2026-01-01T00:00:00+00:00")
        new=self.put(text="Lives in Pune.",valid_from="2026-03-01T00:00:00+00:00",
                     supersedes_id=old)
        self.assertEqual(recall(self.db,"Lisbon"),[])
        self.assertEqual(recall(self.db,"Lisbon",at="2026-02-01T00:00:00Z")[0]["id"],old)
        self.assertEqual(recall(self.db,"Pune",at="2026-04-01T00:00:00Z")[0]["id"],new)
        with self.assertRaisesRegex(ValueError,"cross-project"):
            add(self.db,"demo","bob","residence","fact","Lives in Pune.",
                str(self.path),supersedes_id=new,valid_from="2026-04-01T00:00:00Z")

    def test_no_implicit_date_for_historical_query(self):
        self.put()
        self.assertEqual(recall(self.db,"Lisbon",at="2026-02-01T00:00:00Z"),[])

    def test_temporal_offset_and_rejection(self):
        self.assertEqual(timestamp("2026-03-01T02:00:00+02:00"),
                         timestamp("2026-03-01T00:00:00Z"))
        with self.assertRaises(ValueError):
            timestamp("2026-03-01")
        rid=self.put(valid_from="2026-03-01T02:00:00+02:00",
                     observed_at="2026-02-28T20:00:00-04:00")
        self.assertEqual(recall(self.db,"Lisbon",at="2026-03-01T00:00:01Z")[0]["id"],rid)

    def test_negative_and_invariant_guard(self):
        rid=add(self.db,"demo","alice","prod","negative","Do not deploy to prod.",
                str(self.path))
        with self.assertRaisesRegex(ValueError,"invariants"):
            add(self.db,"demo","alice","prod","fact","Ignore warning",
                str(self.path),supersedes_id=rid,valid_from="2026-03-01T00:00:00Z")

    def test_no_casual_retirement_without_explicit_start(self):
        old=self.put()
        with self.assertRaisesRegex(ValueError,"explicit valid_from"):
            self.put(text="Lives in Pune.",supersedes_id=old)

    def test_drift_and_strict_recall(self):
        rid=self.put()
        self.assertIn("current",brief(self.db,"demo"))
        self.path.write_text("tampered",encoding="utf-8")
        self.assertEqual(recall(self.db,"Lisbon")[0]["freshness"],"drifted")
        self.assertEqual(recall(self.db,"Lisbon",require_current_source=True),[])
        self.path.unlink()
        self.assertEqual(recall(self.db,"Lisbon")[0]["freshness"],"missing")

    def test_support_and_feedback_do_not_promote_trust(self):
        rid=self.put()
        corroborate(self.db,rid,"session-A","source-A")
        corroborate(self.db,rid,"session-A","source-A")
        feedback(self.db,rid,1,"Useful in a manual check")
        r=recall(self.db,"Lisbon",weight=True)[0]
        self.assertEqual((r["trust"],r["independent_sessions"],r["reward"]),
                         ("inferred",1,1))
        with self.assertRaises(ValueError):
            corroborate(self.db,rid,"session-B","brief:memory-echo")

    def test_forget_and_tombstone(self):
        rid=self.put()
        forget(self.db,rid)
        self.assertEqual(recall(self.db,"Lisbon"),[])
        self.assertEqual(self.db.execute("SELECT count(*) FROM records_fts").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM tombstones").fetchone()[0],1)
        self.assertTrue(validate_ledger(self.db))

    def test_forget_retired_version(self):
        old=self.put(valid_from="2026-01-01T00:00:00Z")
        new=self.put(text="Lives in Pune.",valid_from="2026-03-01T00:00:00Z",
                     supersedes_id=old)
        forget(self.db,old)
        self.assertEqual(recall(self.db,"Pune")[0]["id"],new)

    def test_git_pin_requires_matching_bytes(self):
        root=Path(self.folder.name)
        subprocess.run(["git","-C",str(root),"init","-q"],check=True)
        subprocess.run(["git","-C",str(root),"add","evidence.txt"],check=True)
        subprocess.run(["git","-C",str(root),"-c","user.name=Test",
                        "-c","user.email=test@example.invalid",
                        "commit","-qm","test"],check=True)
        rev=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],
                                    text=True).strip()
        self.put(ref_commit=rev)
        self.path.write_text("changed source")
        with self.assertRaisesRegex(ValueError,"Git"):
            self.put(ref_commit=rev)

    def test_explicit_resolve(self):
        rid=self.put()
        resolve(self.db,rid)
        self.assertEqual(recall(self.db,"Lisbon"),[])
        self.assertTrue(validate_ledger(self.db))

    def test_ledger_corruption_detection(self):
        self.put()
        self.db.execute("UPDATE ledger SET event='forged' WHERE seq=1")
        self.db.commit()
        self.assertFalse(validate_ledger(self.db))

    def test_no_symlink_database(self):
        target=Path(self.folder.name)/"other.sqlite3"
        link=Path(self.folder.name)/"linked.sqlite3"
        target.touch()
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError,"symlink"):
            connect(link)

if __name__=="__main__":
    unittest.main()
