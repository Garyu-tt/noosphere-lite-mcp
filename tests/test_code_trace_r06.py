"""R06 CodeTrace tests against synthetic AST observations only."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from noosphere_lite.code_trace_r06 import inspect_code


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "semantic.sqlite3"
        self.sha = "a" * 64
        self.body = "b" * 64
        with sqlite3.connect(self.path) as c:
            c.executescript("""
            CREATE TABLE funcs(
              id TEXT PRIMARY KEY, project TEXT,path TEXT,lang TEXT,qualname TEXT,
              name TEXT,kind TEXT,line INT,end_line INT,args TEXT,returns TEXT,
              branch_count INT,source_sha256 TEXT,source_status TEXT,observed_at TEXT);
            CREATE TABLE calls(caller TEXT,target TEXT,line INT,resolution TEXT,
              callee TEXT,source_sha256 TEXT,
              PRIMARY KEY(caller,target,line));
            CREATE TABLE twins(body_hash TEXT,func_id TEXT,project TEXT,status TEXT,
              PRIMARY KEY(body_hash,func_id));
            """)
            for fid, project, name in [
                ("fn:a", "first", "builder"), ("fn:b", "first", "helper"),
                ("fn:c", "other", "caller"), ("fn:d", "other", "clone")]:
                c.execute(
                    "INSERT INTO funcs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fid, project, "source.py", "python", name, name, "function",
                     10, 18, "arg", "str", 2, self.sha,
                     "parsed_ast_not_runtime_verified", "2026-11-09T00:00:00+00:00"))
            c.execute("INSERT INTO calls VALUES(?,?,?,?,?,?)",
                      ("fn:a", "helper", 12, "same_module_name_candidate", "fn:b", self.sha))
            c.execute("INSERT INTO calls VALUES(?,?,?,?,?,?)",
                      ("fn:c", "builder", 31, "same_module_name_candidate", "fn:a", self.sha))
            c.execute("INSERT INTO calls VALUES(?,?,?,?,?,?)",
                      ("fn:a", "dynamic", 15, "attribute_name_only", None, self.sha))
            for fid, project in [("fn:a", "first"), ("fn:d", "other")]:
                c.execute("INSERT INTO twins VALUES(?,?,?,?)",
                          (self.body, fid, project, "syntactic_body_match_unverified"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_dependencies_incoming_and_duplicates(self):
        x = inspect_code(self.path, "fed:semantic:fn:a", depth=2)
        self.assertEqual(x["root"]["qualname"], "builder")
        self.assertEqual({v["ref"] for v in x["functions"]},
                         {"fed:semantic:fn:a", "fed:semantic:fn:b", "fed:semantic:fn:c"})
        self.assertEqual(len(x["calls"]), 2)
        self.assertTrue(all("unverified" in c["status"] for c in x["calls"]))
        self.assertEqual(x["unresolved_calls"][0]["target_name"], "dynamic")
        self.assertEqual(x["ast_duplicate_candidates"][0]["project"], "other")
        self.assertFalse(x["truth_guaranteed"])
        self.assertFalse(x["truncated"])

    def test_preserves_indexed_provenance(self):
        x = inspect_code(self.path, "fn:a")
        self.assertEqual(x["root"]["indexed_source_status"], "parsed_ast_not_runtime_verified")
        self.assertEqual(x["root"]["source_status"], "static_ast_not_runtime_verified")

    def test_bool_bounds_rejected(self):
        for kw in ({"depth": True}, {"limit": True}):
            with self.assertRaises(ValueError):
                inspect_code(self.path, "fn:a", **kw)

    def test_outgoing_only(self):
        x = inspect_code(self.path, "fn:a", depth=2, include_incoming=False)
        self.assertEqual({v["id"] for v in x["functions"]}, {"fn:a", "fn:b"})

    def test_depth_zero(self):
        x = inspect_code(self.path, "fn:a", depth=0)
        self.assertEqual(len(x["calls"]), 0)
        self.assertEqual(len(x["functions"]), 1)

    def test_bounded_node_limit(self):
        x = inspect_code(self.path, "fn:a", depth=3, limit=2)
        self.assertTrue(x["truncated"])
        self.assertLessEqual(len(x["functions"]), 2)

    def test_unknown(self):
        x = inspect_code(self.path, "fn:missing")
        self.assertIsNone(x["root"])
        self.assertFalse(x["truth_guaranteed"])

    def test_bad_inputs_fail_closed(self):
        for value in ("../etc/passwd", "fn:a;DROP TABLE funcs", "fed:semantic:secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inspect_code(self.path, value)
        for d in (-1, 4, 2.2):
            with self.assertRaises(ValueError):
                inspect_code(self.path, "fn:a", depth=d)
        with self.assertRaises(ValueError):
            inspect_code(self.path, "fn:a", limit=1000)

    def test_read_only(self):
        inspect_code(self.path, "fn:a")
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM funcs").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
