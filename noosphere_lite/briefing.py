"""Read-only encrypted-vault project briefings and deterministic source-path cards.

No plaintext index and no filesystem fetches. These surfaces never create links,
approve claims, infer project membership, or elevate source matches into truth.
Project tags/scope are organizational selectors, NOT access-control boundaries.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .evidence import EvidenceGate
from .vault import MemoryVault, VaultError, _utc_instant

_PROJECT = re.compile(r"[A-Za-z0-9_.:-]{1,48}\Z")
_PRIORITY = {
    "negative": 0,
    "invariant": 1,
    "open_loop": 2,
    "decision": 3,
    "fact": 4,
}
_MAX_TEXT = 2_000


def _scope(value: str) -> str:
    if not isinstance(value, str) or not _PROJECT.fullmatch(value):
        raise VaultError("project must be a 1..48-character identifier")
    return value


def _bounded(limit: int, max_chars: int) -> tuple[int, int]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise VaultError("limit must be 1..50")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1_000 <= max_chars <= 24_000:
        raise VaultError("max_chars must be 1000..24000")
    return limit, max_chars


def _source_ref(path: str) -> str:
    # Exact, caller-owned label. This is never opened on the host filesystem.
    if not isinstance(path, str) or not 1 <= len(path) <= 500 or "\x00" in path:
        raise VaultError("invalid source reference")
    return path


def _validity(node: dict, at: datetime, historical: bool) -> str:
    start = node.get("valid_from")
    end = node.get("valid_to")
    if historical and start is None and end is None:
        return "unknown_historical_validity"
    try:
        if start is not None and datetime.fromisoformat(_utc_instant(start)) > at:
            return "outside_validity"
        if end is not None and datetime.fromisoformat(_utc_instant(end)) <= at:
            return "outside_validity"
    except (ValueError, TypeError, OverflowError, VaultError):
        return "malformed_validity"
    return "eligible"


def _view(node: dict) -> dict:
    return {
        "id": node["id"],
        "kind": node["kind"],
        "title": node["title"],
        "text": node["body"],
        "source_ref": node.get("source") or None,
        "source_verified": False,
        "trust": "unreviewed_memory",
        "recorded_at": node.get("recorded_at", node.get("created")),
        "observed_at": node.get("observed_at"),
        "valid_from": node.get("valid_from"),
        "valid_to": node.get("valid_to"),
    }


def _sort(node: dict):
    return (_PRIORITY.get(node.get("kind"), 99),
            -_sort_time(node), node["id"])


def _sort_time(node: dict):
    try:
        value = _utc_instant(node.get("recorded_at") or node.get("created"))
        return datetime.fromisoformat(value).timestamp() if value else 0.0
    except (ValueError, TypeError, OverflowError, OSError, VaultError):
        return 0.0


def _pack(rows: list[dict], budget: int, limit: int) -> tuple[list[dict], int, int]:
    kept, omitted, used = [], 0, 0
    for row in rows:
        size = len(json.dumps(row, ensure_ascii=False)) + 64
        if size > _MAX_TEXT or used + size > budget or len(kept) >= limit:
            omitted += 1
            continue
        kept.append(row)
        used += size
    return kept, omitted, used


class MemoryBriefings:
    """Scoped, fail-closed read views over the existing NLV1 AES-GCM vault."""

    def __init__(self, vault: MemoryVault):
        self.vault = vault

    def briefing(self, project: str, *, at: str | None = None,
                 limit: int = 20, max_chars: int = 12_000,
                 include_evidence: bool = True) -> dict:
        project = _scope(project)
        limit, max_chars = _bounded(limit, max_chars)
        when = _utc_instant(at)
        moment = datetime.fromisoformat(when) if when else datetime.now(timezone.utc)
        if not isinstance(include_evidence, bool):
            raise VaultError("include_evidence must be boolean")

        # Never read plaintext sidecar databases, file paths or untrusted resources.
        state = self.vault._snapshot()
        candidates, review_required, omitted_invalid = [], [], {}
        for node in state.nodes.values():
            if node.get("archived") or node.get("kind") not in _PRIORITY:
                continue
            if "project:" + project not in node.get("tags", []):
                continue
            status = node.get("status", "current")
            validity = _validity(node, moment, historical=(when is not None))
            if status != "current" or validity in ("unknown_historical_validity",
                                                    "malformed_validity"):
                reason = ("stale" if status != "current" else validity)
                review_required.append({
                    "id": node["id"], "kind": node["kind"],
                    "title": node["title"], "reason": reason,
                })
                continue
            if validity == "outside_validity":
                omitted_invalid["outside_validity"] = omitted_invalid.get(
                    "outside_validity", 0) + 1
                continue
            candidates.append(node)

        candidates.sort(key=_sort)
        records = [_view(n) for n in candidates]
        # Reserve room for metadata, reviews and (optionally) sourced observations.
        records_budget = max_chars // (2 if include_evidence else 1)
        selected, omitted, used = _pack(records, records_budget, limit)
        # Review rows contain only ID/title/reason; keep bounded without truncation.
        review_required.sort(key=lambda x: (x["kind"], x["id"]))
        reviews, omitted_reviews, _ = _pack(review_required, max(500,max_chars//6), limit)

        gate = None
        source_matched = []
        dropped_evidence = 0
        if include_evidence:
            gate = EvidenceGate(self.vault).query("", scope=project, as_of=when, limit=50)
            # This path holds only source-matched candidates; no claim of truth.
            evidence_budget = max_chars - used - 1800
            source_matched, dropped_evidence, _ = _pack(
                gate["facts"], max(0, evidence_budget), limit)
        result = {
            "project": project,
            "at": when,
            "records": selected,
            "review_required": reviews,
            "source_matched_unreviewed": source_matched,
            "evidence_state": gate["status"] if gate else "not_requested",
            "evidence_conflicts": gate["conflicts"] if gate else [],
            "counts": {
                "record_candidates": len(records),
                "record_omitted": omitted,
                "review_candidates": len(review_required),
                "review_omitted": omitted_reviews,
                "evidence_omitted": dropped_evidence,
                "gate_truncated": bool(gate["truncated"]) if gate else False,
                "excluded_outside_validity": omitted_invalid.get("outside_validity",0),
                "evidence_rejected_by_gate": gate["rejected"] if gate else {},
            },
            "truncated": bool(omitted or omitted_reviews or dropped_evidence
                              or (gate and gate["truncated"])),
            "warning": (
                "Project tag and evidence scope are filters, not ACLs. "
                "Ordinary memory notes are unreviewed; source-matched evidence is "
                "not independent truth verification. No host files were read."
            ),
        }
        # Hard bound the serialized response, never truncate an invariant's text.
        while len(json.dumps(result, ensure_ascii=False)) > max_chars:
            for field, counter in (
                ("source_matched_unreviewed", "evidence_omitted"),
                ("records", "record_omitted"),
                ("review_required", "review_omitted"),
            ):
                if result[field]:
                    result[field].pop()
                    result["counts"][counter] += 1
                    result["truncated"] = True
                    break
            else:
                raise VaultError("response cannot fit max_chars")
        return result

    def by_source(self, project: str, source_ref: str, *,
                  limit: int = 20, max_chars: int = 12_000) -> dict:
        project = _scope(project)
        source_ref = _source_ref(source_ref)
        limit, max_chars = _bounded(limit, max_chars)
        state = self.vault._snapshot()
        matched = []
        for node in state.nodes.values():
            if node.get("archived") or node.get("kind") not in _PRIORITY:
                continue
            if "project:" + project not in node.get("tags", []):
                continue
            if node.get("source") != source_ref:
                continue
            matched.append(node)
        matched.sort(key=_sort)
        rows = [{**_view(n), "status": n.get("status", "current"),
                 "needs_review": n.get("status", "current") != "current"}
                for n in matched]
        selected, omitted, _ = _pack(rows, max_chars - 500, limit)
        result = {
            "project": project,
            "source_ref": source_ref,
            "records": selected,
            "matched": len(matched),
            "omitted": omitted,
            "truncated": omitted > 0,
            "source_verified": False,
            "warning": (
                "Exact source label only: no path normalization, file read, "
                "Git check or proof of source freshness. Review stale notes."
            ),
        }
        while len(json.dumps(result, ensure_ascii=False)) > max_chars:
            if not result["records"]:
                raise VaultError("response cannot fit max_chars")
            result["records"].pop()
            result["omitted"] += 1
            result["truncated"] = True
        return result
