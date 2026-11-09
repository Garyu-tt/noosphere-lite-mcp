"""R06 bounded CodeTrace: explain Python AST function dependencies and duplicate candidates.

Pure read-only stdlib module. Never imports indexed projects, executes source
code, contacts external agents, or concludes that a static call is a verified
runtime dependency. The caller controls all database paths.
"""
from __future__ import annotations

from collections import deque
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
import re
import sqlite3

ID = re.compile(r"^(?:fed:semantic:)?fn:[a-zA-Z0-9_-]{1,80}$")
MAX_DEPTH = 3
MAX_NODES = 60


def _connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=8)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _function(db: sqlite3.Connection, ident: str) -> dict | None:
    row = db.execute(
        """SELECT id,project,path,lang,qualname,name,kind,line,end_line,args,
                  returns,branch_count,source_sha256,source_status,observed_at
           FROM funcs WHERE id=?""", (ident,)).fetchone()
    if row is None:
        return None
    obj = dict(row)
    obj["ref"] = "fed:semantic:" + ident
    obj["truth_guaranteed"] = False
    obj["indexed_source_status"] = obj["source_status"]
    obj["source_status"] = "static_ast_not_runtime_verified"
    return obj


def inspect_code(semantic_path: Path, ref: str, *,
                 depth: int = 2, limit: int = 30,
                 include_incoming: bool = True) -> dict:
    """Bounded graph walk with SHA evidence, unresolved calls and AST duplicates.

    A local reference such as fed:semantic:fn:... maps to one indexed Python
    function. BFS follows only statically resolved *candidate* call endpoints.
    Dynamic dispatch and most external/imported calls are not discoverable.
    """
    if not isinstance(ref, str) or not ID.fullmatch(ref):
        raise ValueError("invalid semantic function reference")
    if type(depth) is not int or not (0 <= depth <= MAX_DEPTH):
        raise ValueError("depth must be 0..3")
    if type(limit) is not int or not (1 <= limit <= MAX_NODES):
        raise ValueError("limit must be 1..60")
    if not isinstance(include_incoming, bool):
        raise ValueError("include_incoming must be boolean")
    native = ref.removeprefix("fed:semantic:")
    with closing(_connect(semantic_path)) as db:
        root = _function(db, native)
        if root is None:
            return {"root": None, "functions": [], "calls": [],
                    "unresolved_calls": [], "ast_duplicate_candidates": [],
                    "truncated": False, "truth_guaranteed": False}

        nodes = {native: root}
        edges = []
        unresolved = []
        queue = deque([(native, 0)])
        visited = {native}
        truncated = False
        seen_edges = set()
        while queue:
            src, hops = queue.popleft()
            if hops >= depth:
                continue
            call_rows = db.execute(
                """SELECT caller,target,line,resolution,callee,source_sha256
                   FROM calls WHERE caller=? ORDER BY line,target LIMIT 121""",
                (src,)).fetchall()
            if len(call_rows) > 120:
                truncated = True
            for row in call_rows[:120]:
                caller, target, line, resolution, callee, digest = row
                if callee is None:
                    if src == native and len(unresolved) < 25:
                        unresolved.append({
                            "caller": "fed:semantic:" + src,
                            "target_name": str(target)[:120], "line": line,
                            "resolution": resolution,
                            "source_sha256": digest,
                            "status": "unresolved_static_call_not_a_verified_target"})
                    continue
                if callee not in nodes:
                    if len(nodes) >= limit:
                        truncated = True
                        continue
                    function = _function(db, callee)
                    if function is None:
                        continue
                    nodes[callee] = function
                key = (caller, callee, line)
                if key not in seen_edges:
                    edges.append({
                        "caller": "fed:semantic:" + caller,
                        "callee": "fed:semantic:" + callee,
                        "line": line, "resolution": resolution,
                        "source_sha256": digest,
                        "status": "unverified_ast_resolution_candidate"})
                    seen_edges.add(key)
                if callee not in visited:
                    visited.add(callee)
                    queue.append((callee, hops + 1))

        # Incoming candidates only for the selected root; no recursive
        # reverse fanout. Incoming edges can point to other projects.
        if include_incoming and depth > 0:
            incoming = db.execute(
                """SELECT caller,callee,line,resolution,source_sha256
                   FROM calls WHERE callee=? ORDER BY caller,line LIMIT 121""",
                (native,)).fetchall()
            if len(incoming) > 120:
                truncated = True
            for caller, callee, line, resolution, digest in incoming[:120]:
                if caller not in nodes:
                    if len(nodes) >= limit:
                        truncated = True
                        continue
                    function = _function(db, caller)
                    if function is None:
                        continue
                    nodes[caller] = function
                key = (caller, callee, line)
                if key not in seen_edges:
                    edges.append({
                        "caller": "fed:semantic:" + caller,
                        "callee": "fed:semantic:" + callee,
                        "line": line, "resolution": resolution,
                        "source_sha256": digest,
                        "status": "unverified_ast_resolution_candidate"})
                    seen_edges.add(key)

        twins = []
        matched_hashes = [
            x[0] for x in db.execute(
                "SELECT body_hash FROM twins WHERE func_id=? ORDER BY body_hash",
                (native,)).fetchall()[:4]
        ]
        for body_hash in matched_hashes:
            # A fingerprint is evidence of AST shape only, not same behavior.
            rows = db.execute(
                """SELECT t.func_id,t.project,f.path,f.qualname,f.source_sha256
                   FROM twins t JOIN funcs f ON f.id=t.func_id
                   WHERE t.body_hash=? AND t.func_id<>?
                   ORDER BY t.project,t.func_id LIMIT 21""",
                (body_hash, native)).fetchall()
            if len(rows) > 20:
                truncated = True
            for row in rows[:20]:
                twins.append({
                    "ref": "fed:semantic:" + row["func_id"],
                    "project": row["project"], "path": row["path"],
                    "qualname": row["qualname"], "body_hash": body_hash,
                    "source_sha256": row["source_sha256"],
                    "status": "unverified_context_dependent_ast_body_match"})
        return {
            "root": root, "functions": list(nodes.values()),
            "calls": edges, "unresolved_calls": unresolved,
            "ast_duplicate_candidates": twins,
            "depth": depth, "node_limit": limit, "truncated": truncated,
            "truth_guaranteed": False,
            "review_gates": [
                "Check current source SHA256 against indexed observations",
                "Resolve dynamic dispatch, imports, globals, side effects and typing",
                "Validate duplicate candidates with characterization tests",
                "Review licensing before code transfer",
                "Run tests and representative target benchmarks before integration",
            ],
            "warning": "AST links and fingerprint matches are static observations, never verified runtime behavior.",
        }
