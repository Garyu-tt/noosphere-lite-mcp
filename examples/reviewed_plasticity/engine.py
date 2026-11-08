"""Reviewed graph plasticity: portable, opt-in reference for Noosphere R04.

This is NOT an authenticated service and NOT part of the encrypted Lite vault.
The caller must authenticate principals and supply an authoritative graph
membership callback. Only explicit independent review may update weights.
No source model or graph files are changed.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
import hashlib
import math
import os
import sqlite3
import stat

MAX_EVIDENCE = 2 * 1024 * 1024
MAX_EDGES_PER_JOB = 4

@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    layer: str = "memory"
    source_ref: str = "declared"

    def key(self) -> tuple[str, str, str, str, str]:
        result = (self.source, self.target, self.relation, self.layer, self.source_ref)
        if any(not isinstance(part, str) or not 1 <= len(part) <= 512
               or any(ord(ch) < 32 for ch in part) for part in result):
            raise ValueError("invalid edge identity")
        return result

def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def confidence_from_status(status: str) -> float:
    status = status.lower()
    if any(word in status for word in
           ("unverified", "candidate", "heuristic", "proposal", "draft")):
        return 0.15
    if status == "source_observation":
        return 0.55
    if status in {"cryptographic_verified", "exact_identity"}:
        return 0.65  # File identity, NOT semantic correctness.
    return 0.35

def effective_weight(base: float, strength: float, utility: float,
                     status: str) -> float:
    values = (base, strength, utility)
    if any(not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in values):
        raise ValueError("invalid weight")
    if not (0 <= strength <= 1 and -0.8 <= utility <= 0.8):
        raise ValueError("out of range weight")
    c = confidence_from_status(status)
    return round(max(0.0, min(base, 10.0)) * (0.5 + 0.5 * strength) *
                 (0.35 + 0.65 * c) * (1.0 + utility), 6)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, requester TEXT NOT NULL, assignee TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open','verified','rejected')),
  reviewer TEXT, review_note TEXT, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS usages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL,
  layer TEXT NOT NULL, source_ref TEXT NOT NULL,
  evidence_relpath TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
  declared_at TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
  applied_at TEXT, revoked_at TEXT,
  UNIQUE(job_id,source,target,relation,layer,source_ref)
);
CREATE TABLE IF NOT EXISTS edge_state (
  source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,
  layer TEXT NOT NULL,source_ref TEXT NOT NULL,
  strength REAL NOT NULL CHECK(strength BETWEEN 0 AND 1),
  utility REAL NOT NULL CHECK(utility BETWEEN -0.8 AND 0.8),
  successes INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,
  last_event_id TEXT,
  PRIMARY KEY(source,target,relation,layer,source_ref)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS feedback_events (
  event_id TEXT PRIMARY KEY,usage_id INTEGER NOT NULL UNIQUE REFERENCES usages(id),
  reviewer TEXT NOT NULL, verdict TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  previous_state TEXT, created_at TEXT NOT NULL,reverted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_usages_ready ON usages(approved,applied_at,revoked_at);
"""

class ReviewedLearner:
    """Local library. Do not expose directly to an untrusted LLM/MCP client."""

    def __init__(self, database: Path, artifact_root: Path,
                 reviewers: set[str], has_edge: Callable[[Edge], bool]):
        self.database = Path(database)
        self.artifact_root = Path(artifact_root).resolve(strict=True)
        if (not self.artifact_root.is_dir() or
                not isinstance(reviewers, set) or
                not reviewers or
                not callable(has_edge)):
            raise ValueError("configure trusted reviewer set and graph verifier")
        self.reviewers = frozenset(reviewers)
        self.has_edge = has_edge
        if self.database.is_symlink():
            raise ValueError("database symlink forbidden")
        parent = self.database.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("database directory must exist and not be symlink")
        if parent.stat().st_mode & 0o077:
            raise ValueError("database directory must be owner-only (0700)")
        old_umask = os.umask(0o077)
        try:
            with closing(sqlite3.connect(str(self.database))) as c:
                c.execute("PRAGMA foreign_keys=ON")
                c.executescript(SCHEMA)
                c.commit()
        finally:
            os.umask(old_umask)
        if self.database.stat().st_mode & 0o077:
            raise ValueError("database file must be private (0600)")

    @contextmanager
    def _connect(self, write: bool = False):
        c = sqlite3.connect(str(self.database), timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                c.execute("BEGIN IMMEDIATE")
            yield c
            if write:
                c.commit()
        except BaseException:
            if write:
                c.rollback()
            raise
        finally:
            c.close()

    def _artifact(self, relpath: str) -> tuple[str, str]:
        if not isinstance(relpath, str) or not 1 <= len(relpath) <= 350:
            raise ValueError("invalid evidence path")
        p = Path(relpath)
        if p.is_absolute() or any(x in {"..", "."} for x in p.parts):
            raise ValueError("evidence path must be relative to artifact root")
        path = self.artifact_root / p
        if not path.resolve(strict=True).is_relative_to(self.artifact_root):
            raise ValueError("evidence escaped artifact root")
        cur = self.artifact_root
        for part in p.parts:
            cur = cur / part
            if cur.is_symlink():
                raise ValueError("evidence symlink forbidden")
        # Open the verified pathname without following a final-component
        # symlink. Check inode metadata again after hashing to catch in-place
        # writes during the read (not a substitute for a trusted artifact host).
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            initial = os.fstat(fd)
            if not stat.S_ISREG(initial.st_mode) or initial.st_size > MAX_EVIDENCE:
                raise ValueError("invalid evidence type/size")
            h = hashlib.sha256()
            with os.fdopen(fd, "rb", closefd=False) as f:
                for block in iter(lambda: f.read(65536), b""):
                    h.update(block)
            final = os.fstat(fd)
            if ((initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) !=
                (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)):
                raise ValueError("evidence changed during read")
        finally:
            os.close(fd)
        return str(p), h.hexdigest()

    def begin_job(self, job_id: str, requester: str, assignee: str) -> None:
        """Host-authenticated coordinator must call this, never a worker."""
        if (not all(isinstance(v, str) and 1 <= len(v) <= 128
                    for v in (job_id, requester, assignee))
                or requester == assignee):
            raise ValueError("invalid job identity")
        with self._connect(True) as c:
            c.execute("INSERT INTO jobs(job_id,requester,assignee,status) VALUES(?,?,?,'open')",
                      (job_id, requester, assignee))

    def declare(self, job_id: str, actor: str, edge: Edge, evidence_relpath: str) -> int:
        """Actor must be bound to a verified identity by the calling host."""
        key = edge.key()
        if not self.has_edge(edge):
            raise ValueError("edge not in authoritative graph")
        relpath, sha = self._artifact(evidence_relpath)
        with self._connect(True) as c:
            job = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not job or job["status"] != "open" or actor != job["assignee"]:
                raise ValueError("only assigned worker on open job may declare")
            count = c.execute("SELECT count(*) FROM usages WHERE job_id=?",
                              (job_id,)).fetchone()[0]
            if count >= MAX_EDGES_PER_JOB:
                raise ValueError("too many declared edges")
            c.execute("""INSERT INTO usages(job_id,source,target,relation,layer,
                        source_ref,evidence_relpath,evidence_sha256,declared_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""", (job_id, *key, relpath, sha, utc()))
            return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])

    def review(self, job_id: str, reviewer: str, accepted: bool,
               usage_ids: list[int], note: str) -> int:
        """Explicit authenticated independent QA: never infer use from success."""
        if type(accepted) is not bool or type(usage_ids) is not list:
            raise ValueError("invalid review")
        if (len(usage_ids) > MAX_EDGES_PER_JOB or
            len(usage_ids) != len(set(usage_ids)) or
            any(type(v) is not int or v <= 0 for v in usage_ids)):
            raise ValueError("invalid usage identifiers")
        if not isinstance(note, str) or not 12 <= len(note) <= 2000:
            raise ValueError("specific review note required")
        with self._connect(True) as c:
            job = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if (not job or job["status"] != "open" or
                reviewer not in self.reviewers or
                reviewer in (job["requester"], job["assignee"])):
                raise ValueError("separate authorized reviewer required")
            for usage_id in usage_ids:
                row = c.execute("SELECT * FROM usages WHERE id=? AND job_id=?",
                                (usage_id, job_id)).fetchone()
                if not row:
                    raise ValueError("usage does not belong to job")
                edge = Edge(*(row[f] for f in
                              ("source", "target", "relation", "layer", "source_ref")))
                if not self.has_edge(edge):
                    raise ValueError("edge no longer in authoritative graph")
                relpath, sha = self._artifact(row["evidence_relpath"])
                if relpath != row["evidence_relpath"] or sha != row["evidence_sha256"]:
                    raise ValueError("evidence digest changed before review")
            c.execute("""UPDATE jobs SET status=?,reviewer=?,review_note=?,reviewed_at=?
                         WHERE job_id=? AND status='open'""",
                      ("verified" if accepted else "rejected", reviewer, note, utc(), job_id))
            for usage_id in usage_ids:
                c.execute("UPDATE usages SET approved=1 WHERE id=?", (usage_id,))
            return len(usage_ids)

    def cycle(self) -> dict:
        """Idempotent, transactional reward updates after independent QA only."""
        outcome = {"applied": 0, "skipped_evidence": 0, "skipped_edge": 0}
        with self._connect(True) as c:
            rows = c.execute("""SELECT u.*,j.status,j.reviewer,j.assignee,j.requester
                        FROM usages u JOIN jobs j ON j.job_id=u.job_id
                        WHERE u.approved=1 AND u.applied_at IS NULL
                        AND u.revoked_at IS NULL ORDER BY u.id""").fetchall()
            for row in rows:
                edge = Edge(*(row[k] for k in
                              ("source", "target", "relation", "layer", "source_ref")))
                if not self.has_edge(edge):
                    outcome["skipped_edge"] += 1
                    continue
                try:
                    relpath, sha = self._artifact(row["evidence_relpath"])
                except (OSError, ValueError):
                    outcome["skipped_evidence"] += 1
                    continue
                if (sha != row["evidence_sha256"] or
                    relpath != row["evidence_relpath"]):
                    outcome["skipped_evidence"] += 1
                    continue
                if (row["status"] not in ("verified", "rejected") or
                    row["reviewer"] not in self.reviewers or
                    row["reviewer"] in (row["requester"], row["assignee"])):
                    continue
                key = edge.key()
                prior = c.execute("""SELECT * FROM edge_state
                      WHERE source=? AND target=? AND relation=? AND layer=?
                      AND source_ref=?""", key).fetchone()
                old = dict(prior) if prior else None
                sign = 1 if row["status"] == "verified" else -1
                strength = min(1.0, max(0.0, (old["strength"] if old else 0.5)
                                       + sign * 0.04))
                utility = min(0.8, max(-0.8, (old["utility"] if old else 0.0)
                                      + sign * 0.08))
                successes = (old["successes"] if old else 0) + (sign > 0)
                failures = (old["failures"] if old else 0) + (sign < 0)
                event_id = "reviewed-usage-" + str(row["id"])
                c.execute("""INSERT INTO edge_state VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source,target,relation,layer,source_ref)
                    DO UPDATE SET strength=excluded.strength,
                       utility=excluded.utility,successes=excluded.successes,
                       failures=excluded.failures,last_event_id=excluded.last_event_id""",
                          (*key, round(strength, 6), round(utility, 6),
                           successes, failures, event_id))
                import json
                c.execute("""INSERT INTO feedback_events
                     (event_id,usage_id,reviewer,verdict,evidence_sha256,
                      previous_state,created_at) VALUES(?,?,?,?,?,?,?)""",
                          (event_id, row["id"], row["reviewer"], row["status"],
                           sha, json.dumps(old) if old else None, utc()))
                c.execute("UPDATE usages SET applied_at=? WHERE id=?",
                          (utc(), row["id"]))
                outcome["applied"] += 1
        return outcome

    def weight(self, edge: Edge, base: float = 1.0,
               source_status: str = "source_observation") -> float:
        key = edge.key()
        with self._connect() as c:
            r = c.execute("""SELECT strength,utility FROM edge_state WHERE
                  source=? AND target=? AND relation=? AND layer=?
                  AND source_ref=?""", key).fetchone()
        return effective_weight(base, r["strength"] if r else 0.5,
                                r["utility"] if r else 0.0, source_status)

    def rollback(self, usage_id: int) -> None:
        """Reverse only the most recent reward for its edge; never auto-replay."""
        import json
        with self._connect(True) as c:
            event = c.execute("""SELECT e.*,u.source,u.target,u.relation,u.layer,
                    u.source_ref FROM feedback_events e
                    JOIN usages u ON e.usage_id=u.id
                    WHERE e.usage_id=? AND e.reverted_at IS NULL""",
                              (usage_id,)).fetchone()
            if not event:
                raise ValueError("no active feedback for usage")
            key = tuple(event[k] for k in
                        ("source", "target", "relation", "layer", "source_ref"))
            now_state = c.execute("""SELECT last_event_id FROM edge_state WHERE
                         source=? AND target=? AND relation=? AND layer=?
                         AND source_ref=?""", key).fetchone()
            if not now_state or now_state["last_event_id"] != event["event_id"]:
                raise ValueError("newer reward exists; revert latest first")
            old = json.loads(event["previous_state"]) if event["previous_state"] else None
            if old is None:
                c.execute("""DELETE FROM edge_state WHERE source=? AND target=?
                             AND relation=? AND layer=? AND source_ref=?""", key)
            else:
                c.execute("""UPDATE edge_state SET strength=?,utility=?,successes=?,
                  failures=?,last_event_id=? WHERE source=? AND target=?
                  AND relation=? AND layer=? AND source_ref=?""",
                          (old["strength"], old["utility"], old["successes"],
                           old["failures"], old["last_event_id"], *key))
            c.execute("UPDATE feedback_events SET reverted_at=? WHERE usage_id=?",
                      (utc(), usage_id))
            c.execute("UPDATE usages SET revoked_at=? WHERE id=?", (utc(), usage_id))

    def status(self) -> dict:
        with self._connect() as c:
            return {
                "jobs": c.execute("SELECT count(*) FROM jobs").fetchone()[0],
                "usages": c.execute("SELECT count(*) FROM usages").fetchone()[0],
                "learning_events": c.execute(
                    "SELECT count(*) FROM feedback_events WHERE reverted_at IS NULL").fetchone()[0],
                "learned_edges": c.execute("SELECT count(*) FROM edge_state").fetchone()[0],
                "model_weights_modified": False,
                "independent_identity_enforced_by": "calling authenticated host",
                "content_encrypted_at_rest": False,
            }
