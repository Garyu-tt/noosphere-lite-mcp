"""Portable federation R04 test suite; uses only synthetic, in-memory data."""
import sqlite3
import unittest

from federation import import_live, import_semantic, stable_id, explain_candidate

class FederationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.executescript("""
        CREATE TABLE nodes(id TEXT PRIMARY KEY,layer TEXT,native_id TEXT,kind TEXT,
                           label TEXT,source_ref TEXT);
        CREATE TABLE edges(src TEXT,dst TEXT,relation TEXT,layer TEXT,source_ref TEXT,
                           status TEXT,occurrences INTEGER DEFAULT 1,
                           weight REAL DEFAULT 1.0,
                           PRIMARY KEY(src,dst,relation,layer,source_ref));
        ATTACH DATABASE ':memory:' AS live;
        CREATE TABLE live.sources(id TEXT,kind TEXT,title TEXT,url TEXT,created_at TEXT);
        CREATE TABLE live.items(source_id TEXT,item_id TEXT,title TEXT,source_url TEXT,
                                content_sha256 TEXT,first_seen_at TEXT,observed_at TEXT);
        CREATE TABLE live.versions(source_id TEXT,item_id TEXT,content_sha256 TEXT,
                                   observed_at TEXT,source_updated_at TEXT,source_url TEXT);
        ATTACH DATABASE ':memory:' AS semantic;
        CREATE TABLE semantic.funcs(id TEXT,project TEXT,path TEXT,qualname TEXT,
                                     lang TEXT,line INTEGER,source_sha256 TEXT,source_status TEXT);
        CREATE TABLE semantic.calls(caller TEXT,callee TEXT,resolution TEXT,
                                     source_sha256 TEXT,line INTEGER);
        CREATE TABLE semantic.twins(body_hash TEXT,func_id TEXT,project TEXT);
        """)
        self.sha1="1"*64
        self.sha2="2"*64
        self.db.execute("""INSERT INTO nodes(id,layer,native_id,kind,label,source_ref)
                           VALUES('code:cap:batch_persistence','code','batch_persistence',
                                  'programming_capability','batch persistence','code')""")
        self.db.execute("""INSERT INTO nodes(id,layer,native_id,kind,label,source_ref)
                           VALUES('code:project:proj-a','code','project:proj-a',
                                  'local_project','proj-a','project')""")
    def tearDown(self):
        self.db.close()
    def sample_live(self):
        self.db.execute("INSERT INTO live.sources VALUES('stackoverflow-demo','stackexchange','Stack Overflow','https://stackoverflow.com','2026-11-09')")
        self.db.execute("INSERT INTO live.items VALUES(?,?,?,?,?,?,?)",(
            'stackoverflow-demo','123','SQLite transaction batching',
            'https://stackoverflow.com/questions/123',self.sha2,
            '2026-11-09T00:01Z','2026-11-09T00:02Z'))
        for ver,observed in ((self.sha1,'2026-11-09T00:01Z'),(self.sha2,'2026-11-09T00:02Z')):
            self.db.execute("INSERT INTO live.versions VALUES(?,?,?,?,?,?)",(
                'stackoverflow-demo','123',ver,observed,None,'https://stackoverflow.com/questions/123'))
    def test_stable_ids_collision_avoidance(self):
        self.assertNotEqual(stable_id("item","a:b","c"), stable_id("item","a","b:c"))
        self.assertEqual(stable_id("item","a","b"), stable_id("item","a","b"))
    def test_live_lineage_and_candidate_are_unverified(self):
        self.sample_live()
        stats=import_live(self.db)
        self.assertEqual(stats,{"sources":1,"items":1,"versions":2,"topic_candidates":1})
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes").fetchone()[0],6)
        self.assertEqual(self.db.execute("SELECT count(*) FROM edges WHERE relation='version_of'").fetchone()[0],2)
        out=explain_candidate(self.db,stable_id("item","stackoverflow-demo","123"))
        self.assertFalse(out["truth_guaranteed"])
        self.assertTrue(all("unverified" in x["status"] for x in out["edges"]))
        # Rebuilding from scratch is the contract, but additive repeat is still idempotent.
        self.assertEqual(import_live(self.db),stats)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes").fetchone()[0],6)
        dangling=self.db.execute(
            """SELECT count(*) FROM edges e LEFT JOIN nodes a ON a.id=e.src
               LEFT JOIN nodes b ON b.id=e.dst WHERE a.id IS NULL OR b.id IS NULL""").fetchone()[0]
        self.assertEqual(dangling,0)
    def test_semantic_functions_project_and_fingerprint(self):
        for fid,project,line in [('fn:a','proj-a',3),('fn:b','proj-b',5),('fn:c','proj-a',18)]:
            self.db.execute("INSERT INTO semantic.funcs VALUES(?,?,?,?,?,?,?,?)",(
                fid,project,'example.py','func_'+fid,'python',line,self.sha1,'parsed_ast'))
        self.db.execute("INSERT INTO semantic.calls VALUES(?,?,?,?,?)",
                        ('fn:a','fn:c','same_module_name_candidate',self.sha1,8))
        self.db.execute("INSERT INTO semantic.calls VALUES(?,?,?,?,?)",
                        ('fn:a','fn:missing','same_module_name_candidate',self.sha1,9))
        for fid,project in [('fn:a','proj-a'),('fn:b','proj-b')]:
            self.db.execute("INSERT INTO semantic.twins VALUES(?,?,?)",(self.sha2,fid,project))
        stats=import_semantic(self.db)
        self.assertEqual(stats["functions"],3)
        self.assertEqual(stats["project_edges"],2)
        self.assertEqual(stats["call_candidates"],1)
        self.assertEqual(stats["body_hubs"],1)
        self.assertEqual(stats["body_candidates"],2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM edges WHERE dst='fed:body:"+self.sha2+"'").fetchone()[0],2)
    def test_stale_call_site_digest_is_not_attached_to_new_source(self):
        for fid in ('fn:a', 'fn:b'):
            self.db.execute("INSERT INTO semantic.funcs VALUES(?,?,?,?,?,?,?,?)",
                            (fid,'proj-a','a.py',fid,'python',1,self.sha1,'parsed_ast'))
        self.db.execute("INSERT INTO semantic.calls VALUES(?,?,?,?,?)",
                        ('fn:a','fn:b','same_module_name_candidate',self.sha2,2))
        self.db.execute("INSERT INTO semantic.calls VALUES(?,?,?,?,?)",
                        ('fn:a','fn:b','same_module_name_candidate','invalid',3))
        stats = import_semantic(self.db)
        self.assertEqual(stats['call_candidates'], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM edges WHERE relation='static_call_candidate'").fetchone()[0], 0)

    def test_source_bound_prevents_partial_graph(self):
        self.sample_live()
        self.db.execute("INSERT INTO live.sources VALUES('another','rss','Another','https://example.org','2026-11-09')")
        before = self.db.execute("SELECT count(*) FROM nodes").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "source bound exceeded"):
            import_live(self.db, max_sources=1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes").fetchone()[0], before)

    def test_boolean_source_bound_rejected(self):
        self.sample_live()
        with self.assertRaisesRegex(ValueError, "invalid bounds"):
            import_live(self.db, max_sources=True)

    def test_bounds_fail_closed(self):
        self.sample_live()
        with self.assertRaisesRegex(ValueError,"bound exceeded"):
            import_live(self.db,max_items=1,max_versions=1)
        with self.assertRaisesRegex(ValueError,"invalid attached schema"):
            import_live(self.db,source_schema="live;DROP TABLE nodes")
    def test_import_live_mid_write_failure_rolls_back_and_preserves_caller(self):
        self.sample_live()
        self.db.execute("CREATE TRIGGER reject_federated_item BEFORE INSERT ON nodes "
                        "WHEN NEW.kind='observed_external_item' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        self.db.execute("INSERT INTO nodes VALUES('caller:marker','test','marker','marker','marker','marker')")
        before = self.db.execute("SELECT count(*) FROM nodes").fetchone()[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'synthetic failure'):
            import_live(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes").fetchone()[0], before)
        self.assertEqual(self.db.execute("SELECT count(*) FROM edges").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes WHERE id='caller:marker'").fetchone()[0], 1)

    def test_import_semantic_mid_write_failure_rolls_back(self):
        self.db.execute("INSERT INTO semantic.funcs VALUES(?,?,?,?,?,?,?,?)",
                        ('fn:sample','proj-a','a.py','f','python',1,self.sha1,'parsed_ast'))
        self.db.execute("CREATE TRIGGER reject_semantic BEFORE INSERT ON nodes "
                        "WHEN NEW.kind='static_function' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        before = self.db.execute("SELECT count(*) FROM nodes").fetchone()[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'synthetic failure'):
            import_semantic(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes").fetchone()[0], before)

    def test_late_version_overflow_is_atomic(self):
        self.sample_live()
        before = (self.db.execute("SELECT count(*) FROM nodes").fetchone()[0],
                  self.db.execute("SELECT count(*) FROM edges").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "version bound exceeded"):
            import_live(self.db, max_versions=1)
        after = (self.db.execute("SELECT count(*) FROM nodes").fetchone()[0],
                 self.db.execute("SELECT count(*) FROM edges").fetchone()[0])
        self.assertEqual(before, after)

    def test_late_call_overflow_is_atomic(self):
        self.db.execute("INSERT INTO semantic.funcs VALUES(?,?,?,?,?,?,?,?)",
                        ('fn:sample','proj-a','a.py','f','python',1,self.sha1,'parsed_ast'))
        for i in range(2):
            self.db.execute("INSERT INTO semantic.calls VALUES(?,?,?,?,?)",
                            ('fn:sample','fn:sample','candidate',self.sha1,i))
        before = self.db.execute("SELECT count(*) FROM nodes").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "call bound exceeded"):
            import_semantic(self.db, max_calls=1)
        self.assertEqual(before, self.db.execute("SELECT count(*) FROM nodes").fetchone()[0])

    def test_no_injection_in_labels(self):
        self.db.execute("INSERT INTO live.sources VALUES('abc','webpage','<script>alert(1)</script>','https://example.org','today')")
        import_live(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM nodes WHERE layer='federated'").fetchone()[0],1)
        # Data remains data. No HTML rendering/eval occurs anywhere here.

if __name__=="__main__":
    unittest.main()
