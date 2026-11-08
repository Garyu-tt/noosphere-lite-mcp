"""Synthetic R05 code-context tests, no production data or network access."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from noosphere_lite.code_context_r05 import plan,_relative_sha,_capabilities
from noosphere_lite.federation_overlay import build

class CodeContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.live=self.root/"live.sqlite3"
        self.semantic=self.root/"semantic.sqlite3"
        self.code=self.root/"code.sqlite3"
        self.overlay=self.root/"overlay.sqlite3"
        self.source=self.root/"sources"
        (self.source/"demo-project").mkdir(parents=True)
        self.body=b"def sqlite_batch_insert():\n    return True\n"
        (self.source/"demo-project"/"module.py").write_bytes(self.body)
        self.sha=hashlib.sha256(self.body).hexdigest()
        with sqlite3.connect(self.live) as c:
            c.executescript("""
            CREATE TABLE sources(id TEXT,kind TEXT,title TEXT,url TEXT,created_at TEXT);
            CREATE TABLE items(source_id TEXT,item_id TEXT,title TEXT,source_url TEXT,
                content_sha256 TEXT,first_seen_at TEXT,observed_at TEXT,
                source_updated_at TEXT,license_hint TEXT,trust TEXT);
            CREATE TABLE versions(source_id TEXT,item_id TEXT,content_sha256 TEXT,
                observed_at TEXT,source_updated_at TEXT,source_url TEXT);
            """)
            c.execute("INSERT INTO sources VALUES(?,?,?,?,?)",
                ("stackoverflow-demo","stackexchange","Stack Overflow",
                 "https://stackoverflow.com","2026-11-09T00:00:00Z"))
            c.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("stackoverflow-demo","1","SQLite batch insert transactions",
                 "https://stackoverflow.com/questions/1","2"*64,
                 "2026-11-09T00:00Z","2026-11-09T00:01Z",None,"CC BY-SA",
                 "unverified_external_observation"))
            c.execute("INSERT INTO versions VALUES(?,?,?,?,?,?)",
                ("stackoverflow-demo","1","2"*64,"2026-11-09T00:01Z",None,
                 "https://stackoverflow.com/questions/1"))
        with sqlite3.connect(self.code) as c:
            c.executescript("""
            CREATE TABLE projects(id TEXT,name TEXT);
            CREATE TABLE capabilities(id TEXT,label TEXT);
            CREATE TABLE recipes(
                id TEXT, capability TEXT,language TEXT,requires TEXT,assumptions TEXT,
                complexity TEXT,tradeoff TEXT,license TEXT,correctness TEXT,benchmark_status TEXT);
            """)
            c.execute("INSERT INTO projects VALUES('project:demo-project','demo-project')")
            c.execute("INSERT INTO capabilities VALUES('batch_persistence','batch persistence')")
            c.execute("INSERT INTO capabilities VALUES('shortest_path','shortest path')")
            c.execute("INSERT INTO recipes VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("rec:batch","batch_persistence","python","stdlib sqlite3",
                 "transactions","O(n)","locking issues","MIT","illustrative","not_benchmarked"))
            c.execute("INSERT INTO recipes VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("rec:shortest","shortest_path","python","stdlib heapq",
                 "nonnegative weights","O(E log V)","heap memory","MIT","illustrative","not_benchmarked"))
        with sqlite3.connect(self.semantic) as c:
            c.executescript("""
            CREATE TABLE funcs(id TEXT,project TEXT,path TEXT,qualname TEXT,name TEXT,
                args TEXT,returns TEXT,doc_excerpt TEXT,line INT,end_line INT,
                lang TEXT,source_sha256 TEXT,observed_at TEXT,source_status TEXT);
            CREATE TABLE calls(caller TEXT,callee TEXT,resolution TEXT,source_sha256 TEXT,line INT);
            CREATE TABLE twins(body_hash TEXT,func_id TEXT,project TEXT);
            """)
            c.execute("INSERT INTO funcs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("fn:one","demo-project","module.py","sqlite_batch_insert",
                 "sqlite_batch_insert","","bool","Batch insert helper",1,2,"python",
                 self.sha,"2026-11-09T00:00Z","parsed_ast_not_runtime_verified"))
        build(self.overlay,self.live,self.semantic,self.code)
    def tearDown(self):
        self.tmp.cleanup()
    def p(self,**kw):
        return plan("sqlite batch insert",overlay=self.overlay,code=self.code,
                    live=self.live,semantic=self.semantic,source_root=self.source,**kw)
    def test_grounded_recipe_and_local_file(self):
        r=self.p(project="demo-project",limit=5)
        self.assertEqual(r["capabilities"],["batch_persistence"])
        self.assertGreaterEqual(len(r["code_candidates"]),1)
        self.assertEqual(r["code_candidates"][0]["source_freshness"],"matches_current_file")
        self.assertEqual(r["code_candidates"][0]["source_sha256"],self.sha)
        self.assertEqual(r["recipes"][0]["eligibility"],"eligible")
        self.assertTrue(r["reference_candidates"])
        self.assertEqual(r["reference_candidates"][0]["license_hint"],"CC BY-SA")
        self.assertFalse(r["truth_guaranteed"])
        self.assertEqual(r["index_receipt"]["dangling_endpoints"],0)
    def test_bounded_and_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"task"):
            self.p_task("")
        with self.assertRaisesRegex(ValueError,"hardware"):
            self.p(hardware="coconut")
        with self.assertRaisesRegex(ValueError,"boolean"):
            self.p(allow_external="yes")
        self.assertLessEqual(len(self.p(limit=500)["code_candidates"]),20)
    def p_task(self,task):
        return plan(task,overlay=self.overlay,code=self.code,
                    semantic=self.semantic,live=self.live)
    def test_dijkstra_preconditions(self):
        r=plan("shortest path",overlay=self.overlay,code=self.code,
               semantic=self.semantic,live=self.live,
               capability="shortest_path",negative_edges=True)
        self.assertEqual(r["recipes"][0]["eligibility"],"ineligible")
        self.assertIn("dijkstra_requires_nonnegative_weights",r["recipes"][0]["conditions"])
    def test_source_drift_and_no_symlink(self):
        (self.source/"demo-project"/"module.py").write_text("changed")
        r=self.p(project="demo-project")
        self.assertEqual(r["code_candidates"][0]["source_freshness"],"stale_source_file")
        original=(self.source/"demo-project"/"module.py")
        original.unlink()
        original.symlink_to(self.root/"secret.txt")
        (self.root/"secret.txt").write_text("private")
        self.assertEqual(_relative_sha(self.source,"demo-project","module.py",self.sha),
                         "symlink_refused")
    def test_russian_task_capability(self):
        self.assertIn("batch_persistence",_capabilities("Оптимизация: пакетная запись в SQLite",None))
        r=self.p_task("пакетная запись")
        self.assertIn("batch_persistence",r["capabilities"])
    def test_injection_is_search_data(self):
        x=self.p_task("sqlite OR DROP TABLE nodes")
        self.assertFalse(x["truth_guaranteed"])
        self.assertTrue(self.overlay.exists())
        with self.assertRaises(ValueError):
            self.p_task("a"*241)

if __name__=="__main__":
    unittest.main()
