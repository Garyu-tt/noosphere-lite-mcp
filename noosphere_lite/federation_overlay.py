"""Portable Noosphere incremental federated overlay R04.

A compact, separately rebuildable SQLite index for external source revisions and
static code call graphs. The authoritative source databases are attached read-only.
No network, model, agents, source execution, user private paths, or auto-merging.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from contextlib import closing
from urllib.parse import quote

from .federation import import_live, import_semantic, explain_candidate

SCHEMA = """
CREATE TABLE nodes(id TEXT PRIMARY KEY,layer TEXT NOT NULL,native_id TEXT NOT NULL,
                   kind TEXT NOT NULL,label TEXT NOT NULL,source_ref TEXT NOT NULL);
CREATE INDEX idx_nodes_layer ON nodes(layer);
CREATE TABLE edges(src TEXT NOT NULL,dst TEXT NOT NULL,relation TEXT NOT NULL,
                   layer TEXT NOT NULL,source_ref TEXT NOT NULL,status TEXT NOT NULL,
                   occurrences INTEGER NOT NULL DEFAULT 1,
                   weight REAL NOT NULL DEFAULT 1.0,
                   PRIMARY KEY(src,dst,relation,layer,source_ref));
CREATE INDEX idx_edges_src ON edges(src);
CREATE INDEX idx_edges_dst ON edges(dst);
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE VIRTUAL TABLE node_fts USING fts5(id UNINDEXED,label,kind,layer UNINDEXED,
               tokenize='unicode61 remove_diacritics 2');
"""

def _ro(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return "file:" + quote(str(path.resolve()),safe="/") + "?mode=ro"

def _fingerprints(paths: dict[str,Path]) -> dict:
    result={}
    for name,p in sorted(paths.items()):
        result[name]=[[x.name,x.stat().st_size,x.stat().st_mtime_ns]
                      for x in (p,Path(str(p)+"-wal")) if x.exists()]
    return result

def connect(path: Path) -> sqlite3.Connection:
    c=sqlite3.connect(_ro(Path(path)),uri=True,timeout=8)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    return c

def stats(path: Path) -> dict:
    with closing(connect(path)) as c:
        rows=[tuple(x) for x in c.execute("SELECT layer,count(*) FROM nodes GROUP BY layer")]
        return {"nodes":c.execute("SELECT count(*) FROM nodes").fetchone()[0],
                "edges":c.execute("SELECT count(*) FROM edges").fetchone()[0],
                "layers":dict(rows),
                "dangling":c.execute("""SELECT count(*) FROM edges e
                   LEFT JOIN nodes a ON a.id=e.src LEFT JOIN nodes b ON b.id=e.dst
                   WHERE a.id IS NULL OR b.id IS NULL""").fetchone()[0],
                "updated_at":c.execute("SELECT value FROM meta WHERE key='updated_at'").fetchone()[0],
                "import_receipt":json.loads(c.execute(
                    "SELECT value FROM meta WHERE key='import_receipt'").fetchone()[0])}

def build(target: Path, live: Path, semantic: Path, code: Path,
          force: bool = False) -> dict:
    """Atomic standalone overlay build with strict source checks.

    A failed build leaves the last good overlay unchanged. The staging file is
    per-process; the service supervisor should also serialize public updates.
    """
    target=Path(target);source_paths={"live":Path(live),"semantic":Path(semantic),"code":Path(code)}
    for path in source_paths.values():_ro(path)
    fingerprints=_fingerprints(source_paths)
    if target.is_file() and not force:
        try:
            with closing(connect(target)) as c:
                previous=json.loads(c.execute("SELECT value FROM meta WHERE key='source_fingerprints'").fetchone()[0])
                if previous==fingerprints:
                    return {"changed":False,**stats(target)}
        except (sqlite3.Error,ValueError,TypeError,KeyError):pass
    target.parent.mkdir(parents=True,exist_ok=True)
    staging=target.with_name(target.name+".building."+str(os.getpid()))
    if staging.exists():
        raise FileExistsError("current process staging already present")
    started=time.monotonic()
    c=sqlite3.connect(str(staging),timeout=30)
    try:
        c.execute("PRAGMA synchronous=FULL")
        c.executescript(SCHEMA)
        for name,path in source_paths.items():
            c.execute("ATTACH DATABASE ? AS "+name,(_ro(path),))
        # The two bridge targets exist as tiny reference hubs, not copied code.
        c.execute("BEGIN")
        c.execute("""INSERT OR IGNORE INTO nodes SELECT
            'code:'||id,'code',id,'local_project',name,
            'codefabric:local_project:'||id FROM code.projects""")
        c.execute("""INSERT OR IGNORE INTO nodes SELECT
            'code:cap:'||id,'code',id,'programming_capability',label,
            'codefabric:capability:'||id FROM code.capabilities""")
        live_receipt=import_live(c)
        semantic_receipt=import_semantic(c)
        c.execute("INSERT INTO node_fts(id,label,kind,layer) SELECT id,label,kind,layer FROM nodes")
        from datetime import datetime,timezone
        updated=datetime.now(timezone.utc).isoformat(timespec="seconds")
        receipt={"live":live_receipt,"semantic":semantic_receipt}
        c.execute("INSERT INTO meta VALUES ('updated_at',?)",(updated,))
        c.execute("INSERT INTO meta VALUES ('source_fingerprints',?)",
                  (json.dumps(fingerprints,sort_keys=True),))
        c.execute("INSERT INTO meta VALUES ('import_receipt',?)",
                  (json.dumps(receipt,sort_keys=True),))
        c.commit()
        missing=c.execute("""SELECT count(*) FROM edges e
          LEFT JOIN nodes a ON a.id=e.src LEFT JOIN nodes b ON b.id=e.dst
          WHERE a.id IS NULL OR b.id IS NULL""").fetchone()[0]
        if missing:raise ValueError("dangling overlay endpoints: "+str(missing))
        if c.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise RuntimeError("overlay SQLite integrity failure")
        for name in source_paths:
            c.execute("DETACH DATABASE "+name)
        c.close()
        staging.chmod(0o600)
        os.replace(staging,target)
        return {"changed":True,"seconds":round(time.monotonic()-started,3),
                "import_receipt":receipt,**stats(target)}
    except BaseException:
        c.close()
        try:staging.unlink(missing_ok=True)
        except OSError:pass
        raise

def search(path: Path, query: str, layer: str|None = None, limit: int = 12) -> list[dict]:
    if layer not in (None,"federated","semantic"):
        raise ValueError("invalid overlay layer")
    if not isinstance(query,str) or len(query)>160:
        raise ValueError("query length exceeded")
    tokens=re.findall(r"[\w-]+",query,flags=re.UNICODE)[:8]
    if not tokens:return []
    fts=" OR ".join('"'+t.replace('"','')+'"' for t in tokens)
    cap=max(1,min(int(limit),50))
    with closing(connect(path)) as c:
        sql="""SELECT n.id,n.label,n.kind,n.layer,n.source_ref,
                 bm25(node_fts) AS rank
                 FROM node_fts JOIN nodes n ON n.id=node_fts.id
                 WHERE node_fts MATCH ?"""
        params=[fts]
        if layer:
            sql+=" AND n.layer=?";params.append(layer)
        sql+=" ORDER BY rank,n.id LIMIT ?";params.append(cap)
        return [{**dict(r),"evidence_status":"unverified_index_observation",
                 "truth_guaranteed":False} for r in c.execute(sql,params)]

def neighbors(path: Path, node_id: str, limit: int = 20) -> dict:
    if not isinstance(node_id,str) or len(node_id)>180:
        raise ValueError("invalid node identifier")
    with closing(connect(path)) as c:
        result=explain_candidate(c,node_id,limit)
        if result["node"] is None:
            return {**result,"neighbors":[]}
        enriched=[]
        for entry in result["edges"]:
            target=entry["dst"] if entry["src"]==node_id else entry["src"]
            row=c.execute("SELECT id,label,kind,layer FROM nodes WHERE id=?",(target,)).fetchone()
            if row is None: continue
            enriched.append({**entry,"neighbor_id":row["id"],
                             "neighbor_label":row["label"],
                             "neighbor_kind":row["kind"],
                             "neighbor_layer":row["layer"],
                             "evidence_status":entry["status"],
                             "truth_guaranteed":False})
        return {**result,"neighbors":enriched}
