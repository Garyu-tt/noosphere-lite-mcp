# SPDX-License-Identifier: GPL-3.0-or-later
"""Noosphere Memory Synthesis R01: optional, plaintext research sidecar.

Original independent implementation inspired by publicly documented research.
Not integrated into the encrypted Noosphere Lite NLV1 vault. Do NOT store
confidential data here: SQLite, WAL, source paths and snippets are unencrypted.
Never treat a matching hash or independent repetition as proof that a fact is true.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unicodedata
import uuid

KINDS = ('fact', 'invariant', 'decision', 'open_loop', 'negative', 'idea', 'limit', 'hypothesis')
TRUST = ('verbatim', 'inferred')
DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS records(
 id TEXT PRIMARY KEY, project TEXT NOT NULL, actor TEXT NOT NULL,
 slot TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
 trust TEXT NOT NULL CHECK(trust IN ('verbatim','inferred')),
 source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL, quote TEXT,
 source_url TEXT, ref_commit TEXT, session_id TEXT,
 recorded_at TEXT NOT NULL, observed_at TEXT,
 valid_from TEXT, valid_to TEXT,
 status TEXT NOT NULL CHECK(status IN ('active','superseded','resolved')),
 supersedes_id TEXT REFERENCES records(id), notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_scope ON records(project,actor,slot,status);
CREATE INDEX IF NOT EXISTS ix_time ON records(valid_from,valid_to);
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
 USING fts5(id UNINDEXED,text,project,actor,slot,tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS support(
 record_id TEXT REFERENCES records(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL,source_id TEXT NOT NULL,
 PRIMARY KEY(record_id,session_id,source_id));
CREATE TABLE IF NOT EXISTS feedback(
 record_id TEXT REFERENCES records(id) ON DELETE CASCADE,
 event_id TEXT PRIMARY KEY,value INTEGER NOT NULL CHECK(value IN (-1,1)),
 reason TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tombstones(record_id TEXT PRIMARY KEY,stamped_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ledger(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,
 record_id TEXT NOT NULL,stamped_at TEXT NOT NULL,
 prev_digest TEXT NOT NULL,digest TEXT NOT NULL);
"""

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def timestamp(value):
    """Normalize offset-aware instants, refusing unknown/naive times."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be an offset-aware ISO-8601 string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone/UTC offset required")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")

def norm(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

def sha(data):
    return hashlib.sha256(data).hexdigest()

def connect(path):
    """Never silently expose an existing user's database via chmod."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_symlink():
        raise ValueError("database symlink refused")
    if not p.exists():
        p.touch(mode=0o600)
    if p.stat().st_mode & 0o077:
        raise ValueError("database must have owner-only permissions")
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(DDL)
    return con

def log(con, event, rid):
    last = con.execute("SELECT digest FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    prev = last[0] if last else "GENESIS"
    stamp = now()
    digest = sha(json.dumps([prev,event,rid,stamp],ensure_ascii=False,separators=(",",":")).encode())
    con.execute("INSERT INTO ledger(event,record_id,stamped_at,prev_digest,digest) VALUES(?,?,?,?,?)",
                (event,rid,stamp,prev,digest))

def validate_ledger(con):
    """Detect accidental editing of the recorded event chain; NOT a signed ledger."""
    prev = "GENESIS"
    for row in con.execute("SELECT * FROM ledger ORDER BY seq"):
        digest = sha(json.dumps([prev,row["event"],row["record_id"],row["stamped_at"]],
                                ensure_ascii=False,separators=(",",":")).encode())
        if row["prev_digest"] != prev or row["digest"] != digest:
            return False
        prev = digest
    return True

def verify_git_reference(source, ref_commit, data):
    if not ref_commit:
        return
    try:
        root = Path(subprocess.run(
            ["git","-C",str(source.parent),"rev-parse","--show-toplevel"],
            check=True,capture_output=True,text=True,timeout=6).stdout.strip())
        relative = source.relative_to(root).as_posix()
        checked = subprocess.run(
            ["git","-C",str(root),"show",f"{ref_commit}:{relative}"],
            capture_output=True,check=True,timeout=9).stdout
    except (subprocess.SubprocessError,ValueError,OSError) as exc:
        raise ValueError("Git revision or source path could not be verified") from exc
    if checked != data:
        raise ValueError("local source bytes differ from pinned Git revision")

def add(con,project,actor,slot,kind,text,source_path,trust="inferred",quote=None,
        source_url=None,ref_commit=None,session_id=None,valid_from=None,
        observed_at=None,supersedes_id=None,notes=""):
    if not all((project,actor,slot,text,source_path)):
        raise ValueError("mandatory value missing")
    if kind not in KINDS or trust not in TRUST:
        raise ValueError("unknown kind or trust class")
    source = Path(source_path).resolve(strict=True)
    if not source.is_file():
        raise ValueError("source is not a file")
    data = source.read_bytes()
    verify_git_reference(source,ref_commit,data)
    if trust == "verbatim":
        if not quote or norm(quote) not in norm(data.decode("utf-8")):
            raise ValueError("verbatim quote not present in source")
        if norm(text) != norm(quote):
            raise ValueError("verbatim text must equal verified quote")
    elif quote is not None and norm(quote) not in norm(data.decode("utf-8",errors="replace")):
        raise ValueError("provided quote not present in source")
    valid_from = timestamp(valid_from)
    observed_at = timestamp(observed_at)
    stamp = now()
    predecessor = None
    if supersedes_id:
        predecessor = con.execute("SELECT * FROM records WHERE id=?",(supersedes_id,)).fetchone()
        if not predecessor or predecessor["status"] != "active":
            raise ValueError("superseded target missing or inactive")
        if (predecessor["project"],predecessor["actor"],predecessor["slot"]) != (project,actor,slot):
            raise ValueError("cross-project/actor/slot supersession prohibited")
        if predecessor["kind"] in ("negative","invariant"):
            raise ValueError("invariants and negative knowledge require explicit resolution")
        if valid_from is None or predecessor["valid_from"] is None:
            raise ValueError("both temporal versions need an explicit valid_from")
        if valid_from < predecessor["valid_from"]:
            raise ValueError("new valid_from precedes predecessor")
    rid = "ms:" + uuid.uuid4().hex
    with con:
        con.execute("""INSERT INTO records(
            id,project,actor,slot,kind,text,trust,source_path,source_sha256,
            quote,source_url,ref_commit,session_id,recorded_at,observed_at,
            valid_from,valid_to,status,supersedes_id,notes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid,project,actor,slot,kind,text,trust,str(source),sha(data),quote,source_url,
             ref_commit,session_id,stamp,observed_at,valid_from,None,"active",supersedes_id,notes))
        con.execute("INSERT INTO records_fts(id,text,project,actor,slot) VALUES(?,?,?,?,?)",
                    (rid,text,project,actor,slot))
        if predecessor:
            con.execute("UPDATE records SET status='superseded',valid_to=? WHERE id=?",
                        (valid_from,supersedes_id))
            log(con,"supersede",supersedes_id)
        log(con,"create",rid)
    return rid

def source_status(row):
    try:
        return "current" if sha(Path(row["source_path"]).read_bytes()) == row["source_sha256"] else "drifted"
    except OSError:
        return "missing"

def resolve(con,rid):
    with con:
        row = con.execute("SELECT status FROM records WHERE id=?",(rid,)).fetchone()
        if not row or row["status"] != "active":
            raise ValueError("record missing or inactive")
        con.execute("UPDATE records SET status='resolved' WHERE id=?",(rid,))
        log(con,"resolve",rid)

def forget(con,rid):
    """Remove database-indexed content, but NOT WAL, backup, source or external copies."""
    with con:
        if not con.execute("SELECT 1 FROM records WHERE id=?",(rid,)).fetchone():
            raise ValueError("record not found")
        con.execute("DELETE FROM records_fts WHERE id=?",(rid,))
        con.execute("UPDATE records SET supersedes_id=NULL WHERE supersedes_id=?",(rid,))
        con.execute("DELETE FROM records WHERE id=?",(rid,))
        con.execute("INSERT OR IGNORE INTO tombstones VALUES(?,?)",(rid,now()))
        log(con,"forget",rid)

def corroborate(con,rid,session_id,source_id):
    if not session_id or not source_id or source_id.startswith(("brief:","recall:")):
        raise ValueError("independent session and original source required")
    with con:
        if not con.execute("SELECT 1 FROM records WHERE id=?",(rid,)).fetchone():
            raise ValueError("record not found")
        con.execute("INSERT OR IGNORE INTO support VALUES(?,?,?)",(rid,session_id,source_id))
        log(con,"corroborate",rid)

def feedback(con,rid,value,reason):
    if value not in (-1,1) or not reason:
        raise ValueError("explicit result and reason required")
    with con:
        if not con.execute("SELECT 1 FROM records WHERE id=?",(rid,)).fetchone():
            raise ValueError("record not found")
        con.execute("INSERT INTO feedback VALUES(?,?,?,?,?)",
                    (rid,uuid.uuid4().hex,value,reason,now()))
        log(con,"feedback",rid)

def recall(con,query,project=None,at=None,limit=5,include_history=False,weight=False,
           require_current_source=False):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    terms = [t for t in query.split() if t]
    if not terms:
        return []
    expression = " OR ".join('"' + t.replace('"','""') + '"' for t in terms[:16])
    stmt = """SELECT r.*,bm25(records_fts) AS bm,
        (SELECT COUNT(DISTINCT session_id) FROM support WHERE record_id=r.id)
            AS independent_sessions,
        (SELECT COALESCE(SUM(value),0) FROM feedback WHERE record_id=r.id)
            AS reward
        FROM records_fts JOIN records r ON r.id=records_fts.id
        WHERE records_fts MATCH ?"""
    args = [expression]
    if project:
        stmt += " AND r.project=?"
        args.append(project)
    at = timestamp(at)
    if at:
        stmt += " AND r.valid_from IS NOT NULL AND r.valid_from<=? AND (r.valid_to IS NULL OR r.valid_to>?)"
        args.extend([at,at])
    elif not include_history:
        stmt += " AND r.status='active'"
    stmt += " ORDER BY bm ASC LIMIT 500"
    matches = con.execute(stmt,args).fetchall()
    scored = []
    for row in matches:
        freshness = source_status(row)
        if require_current_source and freshness != "current":
            continue
        boost = max(-2,min(2,row["reward"])) * 0.02 if weight else 0.0
        scored.append((row["bm"]-boost,row,freshness))
    scored.sort(key=lambda item:(item[0],item[1]["id"]))
    return [{**dict(row),"freshness":freshness,"score":float(score)}
            for score,row,freshness in scored[:limit]]

def brief(con,project,limit=16):
    rows = con.execute("""SELECT * FROM records WHERE project=? AND status='active'
        ORDER BY CASE kind WHEN 'negative' THEN 0 WHEN 'invariant' THEN 1
        WHEN 'open_loop' THEN 2 WHEN 'decision' THEN 3 ELSE 4 END,
        recorded_at DESC LIMIT ?""",(project,limit)).fetchall()
    lines = ["NOOSPHERE MEMORY BRIEFING: "+project,
             "Unverified statements remain unverified. Current source hash is not fact validation."]
    for row in rows:
        freshness = source_status(row)
        independent = con.execute(
            "SELECT COUNT(DISTINCT session_id) FROM support WHERE record_id=?",
            (row["id"],)).fetchone()[0]
        lines.append(f'[{freshness}; {row["trust"]}; sessions={independent}] '
                     f'{row["kind"]}/{row["actor"]}/{row["slot"]}: '
                     f'{row["text"]} ({row["id"]})')
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",default=str(Path(__file__).with_name("memory_synthesis.sqlite3")))
    sub = parser.add_subparsers(dest="cmd",required=True)
    addp = sub.add_parser("add")
    for name in ("project","actor","slot","kind","text","source_path"):
        addp.add_argument("--"+name.replace("_","-"),required=True)
    for name in ("trust","quote","source_url","ref_commit","session_id","valid_from",
                 "observed_at","supersedes_id","notes"):
        addp.add_argument("--"+name.replace("_","-"))
    rec = sub.add_parser("recall")
    rec.add_argument("query")
    rec.add_argument("--project")
    rec.add_argument("--at")
    rec.add_argument("--limit",type=int,default=5)
    rec.add_argument("--include-history",action="store_true")
    rec.add_argument("--feedback-experiment",action="store_true")
    rec.add_argument("--require-current-source",action="store_true")
    briefing = sub.add_parser("brief")
    briefing.add_argument("project")
    briefing.add_argument("--limit",type=int,default=16)
    for name in ("resolve","forget"):
        sub.add_parser(name).add_argument("record_id")
    supporting = sub.add_parser("corroborate")
    supporting.add_argument("record_id")
    supporting.add_argument("session_id")
    supporting.add_argument("source_id")
    fb = sub.add_parser("feedback")
    fb.add_argument("record_id")
    fb.add_argument("value",type=int)
    fb.add_argument("reason")
    sub.add_parser("audit")
    args = parser.parse_args()
    db = connect(args.db)
    try:
        if args.cmd == "add":
            fields = ("project","actor","slot","kind","text","source_path","trust",
                      "quote","source_url","ref_commit","session_id","valid_from",
                      "observed_at","supersedes_id","notes")
            print(add(db,**{key:getattr(args,key) for key in fields
                            if getattr(args,key,None) is not None}))
        elif args.cmd == "recall":
            print(json.dumps(recall(db,args.query,args.project,args.at,args.limit,
                                    args.include_history,args.feedback_experiment,
                                    args.require_current_source),ensure_ascii=False,indent=2))
        elif args.cmd == "brief":
            print(brief(db,args.project,args.limit))
        elif args.cmd == "resolve":
            resolve(db,args.record_id)
            print("resolved")
        elif args.cmd == "forget":
            forget(db,args.record_id)
            print("record deleted from sidecar, external copies NOT erased")
        elif args.cmd == "corroborate":
            corroborate(db,args.record_id,args.session_id,args.source_id)
            print("support recorded; epistemic trust unchanged")
        elif args.cmd == "feedback":
            feedback(db,args.record_id,args.value,args.reason)
            print("feedback recorded; epistemic trust unchanged")
        elif args.cmd == "audit":
            statuses = {row[0]:row[1] for row in db.execute(
                "SELECT status,count(*) FROM records GROUP BY status")}
            freshness = {key:0 for key in ("current","drifted","missing")}
            for row in db.execute("SELECT * FROM records"):
                freshness[source_status(row)] += 1
            print(json.dumps({"ledger_valid":validate_ledger(db),"records":statuses,
                              "source_states":freshness,
                              "tombstones":db.execute("SELECT count(*) FROM tombstones")
                              .fetchone()[0]},indent=2))
    except (ValueError,sqlite3.Error,OSError,UnicodeError) as exc:
        print("ERROR:",exc,file=sys.stderr)
        sys.exit(2)
    finally:
        db.close()

if __name__ == "__main__":
    main()
