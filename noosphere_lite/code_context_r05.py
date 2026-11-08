"""Noosphere CodeContext R05: evidence-grounded reusable-code shortlist.

Portable Python + SQLite, no network, credentials, agent calls, code execution,
file mutation, or assumed semantic equivalence. Public and owner-private copies
must stay identical. Inputs are pre-existing read-only catalogs and a compact
federated overlay.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import quote

from .federation import CAPABILITY_ALIASES, stable_id
from .federation_overlay import search as overlay_search, stats as overlay_stats

TOKEN = re.compile(r"[\w]+",re.UNICODE)
SHA256 = re.compile(r"^[a-f0-9]{64}$")
KNOWN_HARDWARE = {"cpu","gpu","any"}
KNOWN_LANGUAGE = {"python","cpp","c","rust","go","javascript","typescript","java","cuda","lua","php","zig","shell"}
MAX_TASK=240
MAX_PROJECT=100
RUSSIAN_CAPABILITIES = {
    "binary_search": ("бинарный поиск", "двоичный поиск"),
    "shortest_path": ("кратчайший путь", "поиск пути", "дейкстра"),
    "priority_queue": ("очередь приоритетов", "приоритетная очередь"),
    "batch_persistence": ("пакетная запись", "пакетная вставка", "транзакции sqlite"),
    "bounded_cache": ("кеширование", "кэширование", "кеш", "кэш"),
    "graph_traversal": ("обход графа", "обход связей"),
    "streaming_hash": ("потоковое хеширование", "хеширование файлов"),
    "sparse_compute": ("разреженная матрица", "разреженные вычисления"),
    "bitpacking_simd": ("битовая упаковка", "симд", "пакетные биты"),
}

def _reader(path: Path):
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    c=sqlite3.connect("file:"+quote(str(path.resolve()),safe="/")+"?mode=ro",
                      uri=True,timeout=8)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    return c

def _tokens(value: str) -> list[str]:
    return list(dict.fromkeys(x.casefold() for x in TOKEN.findall(value)
             if len(x)>1 and x.casefold() not in {
                "and","the","for","with","from","в","и","на","для","от","the","into"
             }))[:12]

def _capabilities(task: str, explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    clean=" "+re.sub(r"[^\w]+"," ",task.casefold())+" "
    matches=[]
    for cap,aliases in CAPABILITY_ALIASES.items():
        if any(" "+re.sub(r"[^\w]+"," ",a.casefold())+" " in clean for a in aliases):
            matches.append(cap)
    for cap,phrases in RUSSIAN_CAPABILITIES.items():
        if any(phrase in task.casefold() for phrase in phrases) and cap not in matches:
            matches.append(cap)
    return matches[:4]

def _compatibility(cap: str, recipe: dict, language: str | None, hardware: str,
                   sorted_input: bool | None, negative_edges: bool | None,
                   allow_external: bool) -> tuple[str,list[str]]:
    reasons=[]
    status="eligible"
    if language and recipe["language"]!=language:
        return "ineligible",["requested_language_mismatch"]
    if recipe["language"]=="cuda" and hardware=="cpu":
        return "ineligible",["cuda_requires_gpu"]
    if hardware=="gpu" and recipe["language"]!="cuda":
        reasons.append("may_run_on_host_cpu_not_selected_gpu")
        status="conditional"
    requirements=(recipe.get("requires") or "").casefold()
    external=any(t in requirements for t in
                 ("crate","numpy","openssl","external","sqlite c api"))
    if external and not allow_external:
        return "ineligible",["unapproved_external_dependency"]
    if cap=="binary_search":
        if sorted_input is False:return "ineligible",["sorted_input_required"]
        if sorted_input is None:reasons.append("prove_sorted_input")
    if cap=="shortest_path":
        if negative_edges is True:return "ineligible",["dijkstra_requires_nonnegative_weights"]
        if negative_edges is None:reasons.append("prove_nonnegative_weights")
    if cap=="bounded_cache":reasons.append("validate_cache_invalidation_and_eviction")
    if cap=="fast_membership":reasons.append("validate_hash_and_equality")
    if cap=="bitpacking_simd":reasons.append("benchmark_accuracy_power_and_target_hardware")
    if reasons:status="conditional"
    return status,reasons

def _relative_sha(root: Path | None, project: str, rel: str,
                  expected: str) -> str:
    """Optional owner-side on-disk freshness check. Never follows symlinks."""
    if root is None:return "not_checked"
    if not SHA256.fullmatch(expected):return "unknown_hash"
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}",project):
        return "invalid_path"
    child=Path(rel)
    if child.is_absolute() or not child.parts or ".." in child.parts or len(child.parts)>14:
        return "invalid_path"
    try:
        trusted_root=Path(root).resolve(strict=True)
        candidate_project=trusted_root/project
        if candidate_project.is_symlink():return "symlink_refused"
        base=candidate_project.resolve(strict=True)
        if not base.is_relative_to(trusted_root):return "invalid_path"
        candidate=base/child
        current=base
        for segment in child.parts:
            current=current/segment
            if current.is_symlink():return "symlink_refused"
        if not candidate.is_file() or not candidate.resolve().is_relative_to(base):
            return "missing_or_outside"
        if candidate.stat().st_size>1_200_000:return "file_too_large"
        digest=hashlib.sha256(candidate.read_bytes()).hexdigest()
        return "matches_current_file" if digest==expected else "stale_source_file"
    except (OSError,ValueError):
        return "missing_or_outside"

def plan(task: str, *, overlay: Path, code: Path, semantic: Path, live: Path,
         project: str = "", language: str | None = "python",
         hardware: str = "cpu", capability: str | None = None,
         sorted_input: bool | None = None, negative_edges: bool | None = None,
         allow_external: bool = False, source_root: Path | None = None,
         limit: int = 10) -> dict[str,Any]:
    """Return a bounded context packet with provenance and validation gates."""
    if not isinstance(task,str) or not 3<=len(task.strip())<=MAX_TASK:
        raise ValueError("task must be 3..240 characters")
    if not isinstance(project,str) or len(project)>MAX_PROJECT:
        raise ValueError("invalid project")
    if language is not None and language not in KNOWN_LANGUAGE:
        raise ValueError("unsupported language")
    if hardware not in KNOWN_HARDWARE:
        raise ValueError("unsupported hardware")
    if capability is not None and not re.fullmatch(r"[a-z][a-z0-9_]{2,80}",capability):
        raise ValueError("invalid capability")
    if not isinstance(allow_external,bool):
        raise ValueError("allow_external must be a boolean")
    if sorted_input not in (None,True,False) or negative_edges not in (None,True,False):
        raise ValueError("invalid precondition type")
    limit=max(1,min(int(limit),20))
    tokens=_tokens(task)
    caps=_capabilities(task,capability)
    if caps and not any(t.isascii() for t in tokens):
        tokens=_tokens(" ".join(" ".join(CAPABILITY_ALIASES.get(c,())[:2]) for c in caps))
    if not tokens:raise ValueError("task has no search terms")
    result={
        "query":task,"project":project or None,"language":language,"hardware":hardware,
        "capabilities":caps,"code_candidates":[],"reference_candidates":[],
        "recipes":[],"index_receipt":{},"required_checks":[],
        "truth_guaranteed":False,
        "candidate_status":"unverified_shortlist_requires_tests_and_review",
    }
    ov=overlay_stats(overlay)
    result["index_receipt"]={"overlay_updated_at":ov["updated_at"],
                             "overlay_nodes":ov["nodes"],"overlay_edges":ov["edges"],
                             "dangling_endpoints":ov["dangling"]}
    # The index is an FTS discovery set, not a best-solution recommender.
    with closing(_reader(semantic)) as sem, closing(_reader(code)) as cod, closing(_reader(live)) as external:
        query=" ".join(tokens[:8])
        semantic_hits=overlay_search(overlay,query,"semantic",min(50,limit*5))
        refs=overlay_search(overlay,query,"federated",min(40,limit*4))
        ranked=[]
        for position,hit in enumerate(semantic_hits):
            if hit["kind"]!="static_function":continue
            func_id=hit["id"].removeprefix("fed:semantic:")
            func=sem.execute(
                """SELECT id,project,path,qualname,name,args,returns,doc_excerpt,
                          line,end_line,lang,source_sha256,observed_at,source_status
                   FROM funcs WHERE id=?""",(func_id,)).fetchone()
            if not func:continue
            f=dict(func)
            if language and f["lang"]!=language:continue
            matching_project=(bool(project) and f["project"]==project)
            name=f["qualname"].casefold()
            overlap=sum(1 for t in tokens if t in name)
            if not overlap and not matching_project:
                continue
            # Explain ranking; static similarity isn't evidence of runtime compatibility.
            is_test=(f["path"].split("/")[-1].startswith("test_") or
                     "/tests/" in "/"+f["path"] or
                     f["qualname"].split(".")[-1].startswith("test_"))
            freshness=_relative_sha(source_root,f["project"],f["path"],
                                    str(f["source_sha256"]))
            score=round(1/(25+position)+1.5*overlap+
                        (2.0 if matching_project else 0.0)-
                        (2.5 if is_test and "test" not in tokens else 0.0)-
                        (3.0 if freshness=="stale_source_file" else 0.0),5)
            adjacency=sem.execute(
                "SELECT resolution,count(*) FROM calls WHERE caller=? GROUP BY resolution",
                (func_id,)).fetchall()
            candidate={
                "id":hit["id"],"project":f["project"],"path":f["path"],
                "qualname":f["qualname"],"language":f["lang"],
                "line":f["line"],"end_line":f["end_line"],"signature":f["args"],
                "return_annotation":f["returns"],"doc_excerpt":f["doc_excerpt"][:350],
                "source_sha256":f["source_sha256"],"observed_at":f["observed_at"],
                "source_freshness":freshness,
                "is_test_function":is_test,
                "static_calls":sum(int(r[1]) for r in adjacency),
                "name_resolved_call_candidates":sum(int(r[1]) for r in adjacency
                     if "candidate" in str(r[0])),
                "score":score,"score_explanation":{
                    "name_token_hits":overlap,"same_project":matching_project,
                    "fts_rank_position":position},
                "trust":"static_ast_observation_not_verified_behavior",
                "required_action":"review_source_contract_and_run_target_tests",
            }
            ranked.append(candidate)
        ranked.sort(key=lambda x:(-x["score"],x["project"],x["path"],x["line"]))
        # Diversity: limit duplicate matches from any single project.
        per_project={}
        for x in ranked:
            owner=x["project"]
            if per_project.get(owner,0)>=max(2,(limit+2)//3):continue
            result["code_candidates"].append(x)
            per_project[owner]=per_project.get(owner,0)+1
            if len(result["code_candidates"])>=limit:break
        ref_ids={h["id"] for h in refs if h["kind"]=="observed_external_item"}
        # Lookups limited by number of indexed observations; no external requests.
        metadata={}
        if ref_ids:
            for row in external.execute(
                """SELECT source_id,item_id,title,source_url,first_seen_at,
                          observed_at,source_updated_at,license_hint,content_sha256,
                          trust FROM items LIMIT 100000"""):
                ident=stable_id("item",row["source_id"],row["item_id"])
                if ident in ref_ids:metadata[ident]=dict(row)
        for hit in refs:
            if hit["id"] not in metadata:continue
            meta=metadata[hit["id"]]
            result["reference_candidates"].append({
                "title":meta["title"],"url":meta["source_url"],
                "source_id":meta["source_id"],
                "observed_at":meta["observed_at"],
                "source_updated_at":meta["source_updated_at"],
                "content_sha256":meta["content_sha256"],
                "license_hint":meta["license_hint"],
                "trust":meta["trust"],
                "status":"external_observation_not_verified_claim",
            })
            if len(result["reference_candidates"])>=min(limit,8):break
        if caps:
            for cap in caps:
                if cod.execute("SELECT 1 FROM capabilities WHERE id=?",(cap,)).fetchone() is None:
                    continue
                for row in cod.execute(
                    """SELECT id,capability,language,requires,assumptions,
                          complexity,tradeoff,license,correctness,benchmark_status
                       FROM recipes WHERE capability=? ORDER BY language""",(cap,)):
                    recipe=dict(row)
                    status,reasons=_compatibility(cap,recipe,language,hardware,
                                   sorted_input,negative_edges,allow_external)
                    result["recipes"].append({**recipe,"eligibility":status,
                                              "conditions":reasons,
                                              "trust":"curated_example_not_proven_optimal"})
    result["recipes"].sort(key=lambda x:(
        {"eligible":0,"conditional":1,"ineligible":2}[x["eligibility"]],
         x["capability"],x["language"],x["id"]))
    result["required_checks"]=[
        "Read exact current source and verify SHA256, API semantics and dependencies",
        "Check source license and attribution before any transfer",
        "Write target characterization and regression tests",
        "Run candidate and baseline on the same representative workload",
        "Record reproducible benchmark and quality evidence",
        "Require reviewed patch before merge or production change",
    ]
    result["warnings"]=[
        "Source files and network pages are not executed or imported.",
        "AST symbol and call associations are static candidates, not runtime identity.",
        "Search relevance does not establish correctness, speed, or suitability.",
        "A source publication date is not the timestamp of an observed fact.",
    ]
    return result
