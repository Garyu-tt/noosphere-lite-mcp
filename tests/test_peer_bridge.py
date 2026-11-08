"""Offline adversarial tests; no internet, credentials or private vault."""
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from noosphere_lite.peer_bridge import (
    JIN_ARTIFACT_PREFIX, PeerError, ingest_jin, ingest_sweet, open_peer_db,
    read_jin_registry, read_skill, read_sweet_export, search_skills, verify_skill,
)


class PeerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "peers.sqlite3"
        self.body = b"---\nname: test-skill\n---\n# Untrusted instructions\n"
        self.sha = hashlib.sha256(self.body).hexdigest()
        self.skill = {
            "name": "test-skill", "description": "SQLite insert with batching",
            "domain": "database", "latest": "1.0.0",
            "releases": [{
                "version": "1.0.0", "status": "active",
                "verification": {"level": "maintainer-validated"},
                "reviewer": "tester", "published_at": "2026-01-01T00:00:00Z",
                "withdrawal": None,
                "artifact": {
                    "path": "shared_skills/releases/1.0.0/test-skill/SKILL.md",
                    "sha256": self.sha, "size_bytes": len(self.body),
                },
            }],
        }

    def registry(self, skill=None):
        return json.dumps({"schema_version": "1.0",
                           "skills": [skill or self.skill]}).encode()

    def archive(self, *files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in files:
                z.writestr(name, content)
        return buf.getvalue()

    def wiki(self, ident="id123", restricted=False):
        return ("---\nid: " + ident + "\nslug: memory-note\n"
                "title: Example Article\ntopic: engineering\n"
                "topicPath:\n  - engineering\n  - backend\n"
                "updatedAt: 2026-01-01T00:00:00Z\n"
                + ("restrictedTags:\n  - private\n" if restricted else "")
                + "---\n\n# Example\nThis is source content.")

    def test_registry_metadata_digest_and_read(self):
        records = read_jin_registry(self.registry(), "2026-11-09T01:00:00+02:00")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["observed_at"], "2026-11-08T23:00:00+00:00")
        self.assertEqual(records[0]["artifact_url"],
                         JIN_ARTIFACT_PREFIX + self.skill["releases"][0]["artifact"]["path"])
        self.assertEqual(verify_skill(records[0], self.body), self.body.decode())
        with self.assertRaisesRegex(PeerError, "digest mismatch"):
            verify_skill(records[0], self.body[:-1] + b"!")
        with patch("noosphere_lite.peer_bridge.fetch_public", return_value=self.body):
            result = read_skill(records[0])
        self.assertTrue(result["sha256_verified"])
        self.assertTrue(result["instructions_are_untrusted"])

    def test_registry_rejects_noncanonical_or_withdrawn(self):
        item = json.loads(json.dumps(self.skill))
        item["releases"][0]["artifact"]["path"] = "../../etc/passwd"
        with self.assertRaisesRegex(PeerError, "artifact"):
            read_jin_registry(self.registry(item))
        item = json.loads(json.dumps(self.skill))
        item["releases"][0]["withdrawal"] = {"reason": "obsolete"}
        with self.assertRaises(PeerError):
            read_jin_registry(self.registry(item))
        item = json.loads(json.dumps(self.skill))
        item["latest"] = None
        self.assertEqual(read_jin_registry(self.registry(item)), [])

    def test_sqlite_version_lineage_and_immutability(self):
        first = read_jin_registry(self.registry(), "2026-11-08T10:00:00Z")
        with open_peer_db(self.db_path) as db:
            self.assertEqual(ingest_jin(db, first)["new_observed_versions"], 1)
            self.assertEqual(ingest_jin(db, first)["new_observed_versions"], 0)
            self.assertEqual(search_skills(db, "sqlite")[0]["name"], "test-skill")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM versions").fetchone()[0], 1)
            bad = [dict(first[0], sha256="a"*64)]
            with self.assertRaisesRegex(PeerError, "immutable"):
                ingest_jin(db, bad)
            self.assertEqual(search_skills(db, "")[0]["sha256"], self.sha)

    def test_sweet_wiki_zip_and_restricted_default(self):
        data = self.archive(("noosphere-export/public.md", self.wiki()),
                            ("noosphere-export/private.md", self.wiki("other", True)),
                            ("noosphere-export/README.md", "# Export"))
        parsed = read_sweet_export(data, "https://wiki.example.org", "2026-11-09T00:00:00Z")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["url"],
                         "https://wiki.example.org/wiki/engineering/backend/memory-note")
        all_rows = read_sweet_export(data, "https://wiki.example.org",
                                     include_restricted=True)
        self.assertEqual(len(all_rows), 2)
        with open_peer_db(self.db_path) as db:
            self.assertEqual(ingest_sweet(db, parsed,
                "https://wiki.example.org")["new_observed_versions"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM versions").fetchone()[0], 1)
            self.assertEqual(ingest_sweet(db, parsed,
                "https://wiki.example.org")["new_observed_versions"], 0)

    def test_zip_attack_and_invalid_origin(self):
        unsafe = self.archive(("../private.md", self.wiki()))
        with self.assertRaisesRegex(PeerError, "unsafe archive"):
            read_sweet_export(unsafe, "https://wiki.example.org")
        good = self.archive(("noosphere-export/note.md", self.wiki()))
        with self.assertRaisesRegex(PeerError, "HTTPS origin"):
            read_sweet_export(good, "http://127.0.0.1:12")
        with self.assertRaisesRegex(PeerError, "HTTPS origin"):
            read_sweet_export(good, "https://user:password@wiki.example.org")
        duplicate = self.archive(("a.md", self.wiki()), ("b.md", self.wiki()))
        with self.assertRaisesRegex(PeerError, "duplicate"):
            read_sweet_export(duplicate, "https://wiki.example.org")

    def test_federation_import_from_peer_db(self):
        from noosphere_lite.federation import import_live
        skills = read_jin_registry(self.registry())
        with open_peer_db(self.db_path) as peers:
            ingest_jin(peers, skills)
        db = sqlite3.connect(":memory:")
        db.executescript("""
            CREATE TABLE nodes(id TEXT PRIMARY KEY,layer TEXT,native_id TEXT,
                kind TEXT,label TEXT,source_ref TEXT);
            CREATE TABLE edges(src TEXT,dst TEXT,relation TEXT,layer TEXT,
                source_ref TEXT,status TEXT,occurrences INTEGER DEFAULT 1,
                weight REAL DEFAULT 1.0,
                PRIMARY KEY(src,dst,relation,layer,source_ref));
        """)
        db.execute("ATTACH DATABASE ? AS peers",
                   (f"file:{self.db_path}?mode=ro",))
        result = import_live(db, "peers")
        self.assertEqual(result["sources"], 1)
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["versions"], 1)
        self.assertEqual(db.execute(
            "SELECT COUNT(*) FROM edges WHERE status LIKE '%unverified%'"
            ).fetchone()[0], 2)
        db.close()


if __name__ == "__main__":
    unittest.main()
