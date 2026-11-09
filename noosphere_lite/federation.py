"""Portable, read-only Noosphere evidence graph federation (R04).

This module contains no local paths, privileged agent interfaces or network access.
It imports observed third-party metadata and static AST evidence into a disposable
metagraph SQLite connection. NEVER use this importer to certify facts or execute
indexed code. The caller controls source permissions, DB attaches and publication.
"""
from __future__ import annotations

import hashlib
import functools
import itertools
import re
import sqlite3
from typing import Any

SAFE_SOURCE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,70}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CAPABILITY_ALIASES = {
    "batch_persistence": ("sqlite", "transaction", "bulk insert", "batch insert"),
    "bounded_cache": ("lru", "cache eviction", "memoization", "cache"),
    "binary_search": ("binary search", "bisect", "lower bound"),
    "shortest_path": ("dijkstra", "astar", "shortest path"),
    "priority_queue": ("heapq", "priority queue", "binary heap"),
    "streaming_hash": ("sha256", "streaming hash", "checksum"),
    "zero_copy_buffer": ("zero copy", "zero-copy", "memoryview"),
    "async_channel": ("message queue", "async channel", "producer consumer"),
    "sparse_compute": ("sparse matrix", "csr", "sparse compute"),
    "bitpacking_simd": ("simd", "dp4a", "bitpacking", "popcount"),
    "graph_traversal": ("graph traversal", "depth first search", "breadth first search"),
    "fast_membership": ("hash set", "hashset", "membership lookup"),
}

def stable_id(kind: str, *parts: object) -> str:
    """Deterministic cross-run IDs, immune to separator collisions in item keys."""
    payload = "\x00".join(str(p) for p in parts).encode("utf-8")
    return "fed:" + kind + ":" + hashlib.sha256(payload).hexdigest()[:32]

def _clean(value: Any, length: int = 400) -> str:
    """Bound untrusted display fields. No untrusted text becomes an instruction."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()[:length]

def _node(db: sqlite3.Connection, ident: str, layer: str,
          native: str, kind: str, label: str, source: str) -> None:
    db.execute(
        """INSERT OR IGNORE INTO nodes(id,layer,native_id,kind,label,source_ref)
           VALUES(?,?,?,?,?,?)""",
        (ident, layer, native, kind, _clean(label), _clean(source,2048)))

def _edge(db: sqlite3.Connection, src: str, dst: str, relation: str,
          layer: str, source: str, status: str) -> None:
    db.execute(
        """INSERT OR IGNORE INTO edges(src,dst,relation,layer,source_ref,status)
           VALUES(?,?,?,?,?,?)""",
        (src,dst,relation,layer,_clean(source,2048),status))

def _aliases(title: str) -> tuple[str, ...]:
    normalized = " " + re.sub(r"[^\w]+", " ", title.casefold()) + " "
    hits = []
    for capability, phrases in CAPABILITY_ALIASES.items():
        if any(" "+re.sub(r"[^\w]+"," ",term.casefold())+" " in normalized
               for term in phrases):
            hits.append(capability)
    return tuple(hits)

_savepoint_ids = itertools.count()

def atomic_graph_import(func):
    """Rollback only this import's writes, preserving the caller's transaction."""
    @functools.wraps(func)
    def wrapped(db, *args, **kwargs):
        name = f"noosphere_import_{next(_savepoint_ids)}"
        db.execute(f"SAVEPOINT {name}")
        try:
            result = func(db, *args, **kwargs)
        except BaseException:
            db.execute(f"ROLLBACK TO SAVEPOINT {name}")
            db.execute(f"RELEASE SAVEPOINT {name}")
            raise
        db.execute(f"RELEASE SAVEPOINT {name}")
        return result
    return wrapped

@atomic_graph_import
def import_live(db: sqlite3.Connection, source_schema: str = "live",
                max_items: int = 30000, max_versions: int = 80000,
                max_sources: int = 10000) -> dict[str,int]:
    """Import external observations without claiming correctness.

    source_schema must name an already attached read-only SQLite database.
    Query values are parameterized and schema alias is checked.
    """
    if not re.fullmatch(r"[a-z][a-z0-9_]*",source_schema):
        raise ValueError("invalid attached schema")
    if (type(max_items) is not int or type(max_versions) is not int or
            type(max_sources) is not int or not 0 < max_sources <= 100000 or
            not 0 < max_items <= 100000 or not 0 < max_versions <= 500000):
        raise ValueError("invalid bounds")
    # Preflight all bounded tables before mutating the destination graph.
    # Otherwise a late versions overflow leaves partially imported items.
    for table, limit, label in (("sources", max_sources, "source"),
                                ("items", max_items, "item"),
                                ("versions", max_versions, "version")):
        count = db.execute(
            f"SELECT count(*) FROM {source_schema}.{table}").fetchone()[0]
        if count > limit:
            raise ValueError(f"federated {label} bound exceeded; refuse partial graph")
    has_caps = {row[0] for row in db.execute(
        "SELECT native_id FROM nodes WHERE layer='code' AND kind='programming_capability'")}
    counts={"sources":0,"items":0,"versions":0,"topic_candidates":0}
    for s in db.execute(f"SELECT id,kind,title,url,created_at FROM {source_schema}.sources"):
        sid,kind,title,url,created=s
        if not SAFE_SOURCE_ID.fullmatch(str(sid)):
            continue
        source_id="fed:source:"+sid
        _node(db,source_id,"federated",sid,"external_source",title,
              url if str(url).startswith("https://") else "source_registry:"+sid)
        counts["sources"]+=1
    rows=db.execute(
        f"""SELECT i.source_id,i.item_id,i.title,i.source_url,
                   i.content_sha256,i.first_seen_at,i.observed_at
            FROM {source_schema}.items i
            ORDER BY i.source_id,i.item_id LIMIT ?""",(max_items+1,)).fetchall()
    if len(rows)>max_items:
        raise ValueError("federated item bound exceeded; refuse partial graph")
    ids: dict[tuple[str,str],str]={}
    for sid,ident,title,url,digest,first,observed in rows:
        sid,ident,digest=str(sid),str(ident),str(digest)
        if not SAFE_SOURCE_ID.fullmatch(sid) or not SHA256.fullmatch(digest):
            continue
        if not str(url).startswith("https://"):
            continue
        source_id="fed:source:"+sid
        if db.execute("SELECT 1 FROM nodes WHERE id=?",(source_id,)).fetchone() is None:
            continue
        item=stable_id("item",sid,ident)
        ids[(sid,ident)]=item
        _node(db,item,"federated",sid+":"+ident,"observed_external_item",
              title,url)
        _edge(db,item,source_id,"observed_from_source","federated",url,
              "unverified_source_metadata")
        counts["items"]+=1
        for capability in _aliases(str(title)):
            if capability not in has_caps:
                continue
            _edge(db,item,"code:cap:"+capability,
                  "possible_reference_for_capability","cross",url,
                  "unverified_title_keyword_candidate")
            counts["topic_candidates"]+=1
    rows=db.execute(
        f"""SELECT source_id,item_id,content_sha256,observed_at,source_updated_at,
                   source_url FROM {source_schema}.versions
            ORDER BY source_id,item_id,observed_at LIMIT ?""",
        (max_versions+1,)).fetchall()
    if len(rows)>max_versions:
        raise ValueError("federated version bound exceeded; refuse partial graph")
    for sid,ident,digest,observed,source_updated,url in rows:
        key=str(sid),str(ident)
        if key not in ids or not SHA256.fullmatch(str(digest)):
            continue
        version=stable_id("version",sid,ident,digest)
        _node(db,version,"federated",str(digest),"observed_revision",
              "sha256:"+str(digest)[:14]+" · indexed "+_clean(observed,40),
              url)
        _edge(db,version,ids[key],"version_of","federated",url,
              "unverified_observed_version_digest_not_fact_verification")
        counts["versions"]+=1
    return counts

@atomic_graph_import
def import_semantic(db: sqlite3.Connection, source_schema: str = "semantic",
                    max_functions: int = 50000, max_calls: int = 150000,
                    max_twins: int = 150000
                    ) -> dict[str,int]:
    """Attach AST function and cautiously resolved call candidates.

    Qualified function names are not runtime-dispatched identities.
    """
    if not re.fullmatch(r"[a-z][a-z0-9_]*",source_schema):
        raise ValueError("invalid attached schema")
    if (type(max_functions) is not int or type(max_calls) is not int or
            type(max_twins) is not int or not 0 < max_twins <= 500000 or
            not 0 < max_functions <= 100000 or not 0 < max_calls <= 500000):
        raise ValueError("invalid bounds")
    # Both bounds must pass before inserting any semantic nodes or edges.
    call_count = db.execute(
        f"SELECT count(*) FROM {source_schema}.calls WHERE callee IS NOT NULL"
    ).fetchone()[0]
    if call_count > max_calls:
        raise ValueError("semantic call bound exceeded; refuse partial graph")
    twin_count = db.execute(f"SELECT count(*) FROM {source_schema}.twins").fetchone()[0]
    if twin_count > max_twins:
        raise ValueError("semantic twin bound exceeded; refuse partial graph")
    count=db.execute(f"SELECT count(*) FROM {source_schema}.funcs").fetchone()[0]
    if count>max_functions:
        raise ValueError("semantic function bound exceeded; refuse partial graph")
    rows=db.execute(
        f"""SELECT id,project,path,qualname,lang,line,source_sha256,source_status
            FROM {source_schema}.funcs ORDER BY id""").fetchall()
    counts={"functions":0,"project_edges":0,"call_candidates":0,
            "body_hubs":0,"body_candidates":0}
    # Reject stale call-site AST evidence from a different source revision.
    caller_digests = {str(fid): str(digest) for fid, _, _, _, _, _, digest, _ in rows
                      if str(fid).startswith("fn:") and SHA256.fullmatch(str(digest))}
    for fid,project,path,qualname,lang,line,digest,status in rows:
        fid=str(fid)
        if not fid.startswith("fn:") or not SHA256.fullmatch(str(digest)):
            continue
        ref="semantic:"+str(digest)+":"+str(line)
        ident="fed:semantic:"+fid
        _node(db,ident,"semantic",fid,"static_function",
              f"{qualname} ({lang}) in {project}/{path}:{line}",ref)
        counts["functions"]+=1
        target="code:project:"+str(project)
        if db.execute("SELECT 1 FROM nodes WHERE id=?",(target,)).fetchone():
            _edge(db,ident,target,"observed_in_local_project","semantic",
                  ref,"static_ast_file_observation")
            counts["project_edges"]+=1
    if db.execute(f"SELECT count(*) FROM {source_schema}.calls WHERE callee IS NOT NULL").fetchone()[0]>max_calls:
        raise ValueError("semantic call bound exceeded; refuse partial graph")
    for caller,callee,resolution,sha,line in db.execute(
        f"""SELECT caller,callee,resolution,source_sha256,line
            FROM {source_schema}.calls WHERE callee IS NOT NULL
            ORDER BY caller,line"""):
        if not SHA256.fullmatch(str(sha)) or caller_digests.get(str(caller)) != str(sha):
            continue  # stale or unprovable call-site evidence
        a,b="fed:semantic:"+str(caller),"fed:semantic:"+str(callee)
        if a==b and resolution=="attribute_name_only": continue
        if db.execute("SELECT 1 FROM nodes WHERE id=?",(a,)).fetchone() is None: continue
        if db.execute("SELECT 1 FROM nodes WHERE id=?",(b,)).fetchone() is None: continue
        _edge(db,a,b,"static_call_candidate","semantic",
              "semantic:"+str(sha)+":"+str(line),
              "ast_name_resolution_unverified")
        counts["call_candidates"]+=1
    # Fingerprint hubs scale linearly with function count (no clique expansion).
    for body_hash,nprojects in db.execute(
        f"""SELECT t.body_hash,count(DISTINCT t.project)
            FROM {source_schema}.twins t
            JOIN {source_schema}.funcs f ON f.id=t.func_id AND f.project=t.project
            GROUP BY t.body_hash HAVING count(DISTINCT t.project)>1 ORDER BY t.body_hash"""):
        if not SHA256.fullmatch(str(body_hash)):continue
        hub="fed:body:"+str(body_hash)
        _node(db,hub,"semantic",str(body_hash),"ast_body_fingerprint",
              "AST body fingerprint "+str(body_hash)[:14],
              "static_ast_fingerprint:"+str(body_hash))
        counts["body_hubs"]+=1
        for (fid,) in db.execute(
            f"""SELECT t.func_id FROM {source_schema}.twins t
                JOIN {source_schema}.funcs f ON f.id=t.func_id AND f.project=t.project
                WHERE t.body_hash=?""",
            (body_hash,)).fetchall():
            ident="fed:semantic:"+str(fid)
            if db.execute("SELECT 1 FROM nodes WHERE id=?",(ident,)).fetchone() is None:
                continue
            _edge(db,ident,hub,"shares_static_ast_fingerprint","semantic",
                  "static_ast_fingerprint:"+str(body_hash),
                  "unverified_context_dependent_duplicate_candidate")
            counts["body_candidates"]+=1
    return counts

def explain_candidate(db: sqlite3.Connection, node_id: str,
                      max_edges: int = 20) -> dict[str,Any]:
    """Bounded provenance explanation. No inferred fact is silently promoted."""
    max_edges=min(50,max(1,int(max_edges)))
    node=db.execute("SELECT id,layer,kind,label,source_ref FROM nodes WHERE id=?",
                    (node_id,)).fetchone()
    if node is None: return {"node":None,"edges":[]}
    edges=db.execute(
        """SELECT src,dst,relation,status,source_ref FROM edges
           WHERE src=? OR dst=? ORDER BY relation,status LIMIT ?""",
        (node_id,node_id,max_edges)).fetchall()
    return {"node":dict(zip(("id","layer","kind","label","source_ref"),node)),
            "edges":[dict(zip(("src","dst","relation","status","source_ref"),r))
                     for r in edges],
            "truth_guaranteed":False,
            "warning":"Graph edges are source observations or explicitly unverified candidates."}
