"""Synthetic public tests for the compact R04 federation overlay."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from noosphere_lite.federation_overlay import build,stats,search,neighbors

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.target=self.root/"out.sqlite3"
        self.live=self.root/"live.sqlite3"
        self.semantic=self.root/"semantic.sqlite3"
        self.code=self.root/"code.sqlite3"
        self.h="a"*64
        with sqlite3.connect(self.code) as c:
            c.executescript("""CREATE TABLE projects(id TEXT,name TEXT);
                CREATE TABLE capabilities(id TEXT,label TEXT);""")
            c.execute("INSERT INTO projects VALUES('project:demo','demo')")
            c.execute("INSERT INTO capabilities VALUES('batch_persistence','batch persistence')")
        with sqlite3.connect(self.live) as c:
            c.executescript("""CREATE TABLE sources(id TEXT,kind TEXT,title TEXT,url TEXT,created_at TEXT);
                CREATE TABLE items(source_id TEXT,item_id TEXT,title TEXT,source_url TEXT,
                                   content_sha256 TEXT,first_seen_at TEXT,observed_at TEXT);
                CREATE TABLE versions(source_id TEXT,item_id TEXT,content_sha256 TEXT,
                                     observed_at TEXT,source_updated_at TEXT,source_url TEXT);""")
            c.execute("INSERT INTO sources VALUES(?,?,?,?,?)",
                      ("public-demo","feed","Demo feed","https://example.org/rss","2026-11-09"))
            c.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)",(
                "public-demo","1","SQLite transaction example","https://example.org/article",
                self.h,"2026-11-09T00:01Z","2026-11-09T00:02Z"))
            c.execute("INSERT INTO versions VALUES(?,?,?,?,?,?)",(
                "public-demo","1",self.h,"2026-11-09T00:02Z",None,
                "https://example.org/article"))
        with sqlite3.connect(self.semantic) as c:
            c.executescript("""CREATE TABLE funcs(id TEXT,project TEXT,path TEXT,qualname TEXT,
                lang TEXT,line INTEGER,source_sha256 TEXT,source_status TEXT);
                CREATE TABLE calls(caller TEXT,callee TEXT,resolution TEXT,source_sha256 TEXT,line INTEGER);
                CREATE TABLE twins(body_hash TEXT,func_id TEXT,project TEXT);""")
            c.execute("INSERT INTO funcs VALUES(?,?,?,?,?,?,?,?)",(
                "fn:foo","demo","demo.py","serialize","python",10,self.h,"parsed_ast"))
    def tearDown(self):
        self.temp.cleanup()
    def test_build_and_search(self):
        result=build(self.target,self.live,self.semantic,self.code)
        self.assertTrue(result["changed"])
        self.assertGreaterEqual(result["nodes"],6)
        self.assertEqual(result["dangling"],0)
        x=search(self.target,"sqlite",layer="federated")
        self.assertTrue(x)
        self.assertFalse(x[0]["truth_guaranteed"])
        y=search(self.target,"serialize",layer="semantic")
        self.assertEqual(len(y),1)
        self.assertEqual(y[0]["kind"],"static_function")
        explain=neighbors(self.target,y[0]["id"])
        self.assertFalse(explain["truth_guaranteed"])
        self.assertTrue(any(edge["relation"]=="observed_in_local_project"
                            for edge in explain["edges"]))
        again=build(self.target,self.live,self.semantic,self.code)
        self.assertFalse(again["changed"])
        self.assertEqual(again["nodes"],result["nodes"])
    def test_source_change_rebuilds(self):
        build(self.target,self.live,self.semantic,self.code)
        with sqlite3.connect(self.live) as c:
            c.execute("UPDATE items SET title='Python SQLite new' WHERE item_id='1'")
        newer=build(self.target,self.live,self.semantic,self.code)
        self.assertTrue(newer["changed"])
        self.assertTrue(search(self.target,"python",layer="federated"))
    def test_failed_source_preserves_last_good(self):
        build(self.target,self.live,self.semantic,self.code)
        baseline=self.target.read_bytes()
        with self.assertRaises(FileNotFoundError):
            build(self.target,self.root/"missing.sqlite3",self.semantic,self.code,force=True)
        self.assertEqual(baseline,self.target.read_bytes())
    def test_unsupported_layer_fails(self):
        build(self.target,self.live,self.semantic,self.code)
        with self.assertRaises(ValueError):
            search(self.target,"sqlite",layer="memory")

if __name__=="__main__":
    unittest.main()
