"""Explicit trust-boundary context: source-grounded observations vs legacy notes.

A source-matched claim is not a verified real-world fact. This adapter prevents
unreviewed general notes from quietly entering the evidence-only context lane.
"""
from __future__ import annotations

import json

from .evidence import EvidenceGate
from .vault import MemoryVault, VaultError


def context(vault: MemoryVault, evidence: EvidenceGate, query: str,
            max_chars: int = 10000, *, source_grounded_only: bool = False,
            scope: str = "default", as_of: str | None = None,
            git_guard=None) -> dict:
    if type(source_grounded_only) is not bool:
        raise VaultError("source_grounded_only must be boolean")
    if type(max_chars) is not int or not 500 <= max_chars <= 40000:
        raise VaultError("max_chars must be 500..40000")
    if source_grounded_only:
        response = evidence.query(query, scope=scope, as_of=as_of, limit=50)
        budget, selected, withheld = max_chars, [], 0
        for fact in response["facts"]:
            # Never truncate source attestations or value hashes: incomplete
            # proof material would be misleading. Skip whole facts instead.
            cost = len(json.dumps(fact, ensure_ascii=False,
                                  sort_keys=True).encode("utf-8")) + 24
            if cost > budget:
                withheld += 1
                continue
            selected.append(fact)
            budget -= cost
        return {
            "query": query, "scope": scope, "as_of": as_of,
            "mode": "source_grounded_only", "facts": selected,
            "memories": [], "status": (
                "conflict" if response["status"] == "conflict" else
                "source_matched_only" if selected else
                "insufficient_context_budget" if withheld else
                "insufficient_evidence"),
            "conflicts": response["conflicts"],
            "rejected": response["rejected"],
            "truncated": response["truncated"] or withheld > 0,
            "withheld_for_budget": withheld,
            "truth_guaranteed": False,
            "independently_verified": False,
            "warning": "Evidence matches a source, not independent world truth. No unreviewed notes included.",
        }
    if as_of is not None:
        raise VaultError("historical context requires source_grounded_only=true")
    result = vault.context(query, max_chars)
    kept, drifted = [], 0
    for memory in result["memories"]:
        memory["evidence_status"] = "unreviewed_legacy_memory"
        memory["truth_guaranteed"] = False
        if git_guard is not None:
            observed = git_guard.status(memory["id"])
            memory["git_provenance"] = observed["status"]
            if observed["status"] == "stale_needs_review":
                drifted += 1
                continue
        kept.append(memory)
    result["memories"] = kept
    result["git_drift_withheld"] = drifted
    result["needs_review"] += drifted
    return {
        **result, "mode": "legacy_unreviewed",
        "truth_guaranteed": False,
        "warning": "General memories are unreviewed notes, not source-grounded facts; use source_grounded_only=true.",
    }
