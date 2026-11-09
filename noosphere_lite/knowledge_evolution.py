"""Optional knowledge evolution primitives; no external graph DB required.

Portability and provenance are separate from the encrypted truth journal.
A graph projection is derived, never an authority or evidence of execution.
"""
from __future__ import annotations

import hashlib
import json
import re

OWNERSHIP_SENTINEL = "\n## End Index Hash\n"
ENRICHMENT_HEADING = "## AI Enrichment\n"
EPISTEMIC_STATES = frozenset({
    "unreviewed", "observation", "inference", "hypothesis",
    "proposal", "decision", "rejected", "superseded", "unresolved",
})

# Advisory vocabulary, not a restriction on historical custom relations.
RELATIONS = {
    "contains": "container -> component",
    "part_of": "component -> whole",
    "calls": "caller -> callee",
    "uses": "consumer -> dependency",
    "depends_on": "dependent -> prerequisite",
    "implements": "implementation -> requirement",
    "tests": "test -> subject",
    "verifies": "evidence -> subject",
    "produces": "activity -> output",
    "derived_from": "claim -> original source",
    "supports": "evidence -> claim",
    "contradicts": "assertion/evidence -> conflicting claim",
    "proposes": "actor -> proposal",
    "authorizes": "decision -> permitted action",
    "executes": "action -> observed execution record",
    "supersedes": "new decision -> earlier decision",
    "related": "entity -> related entity (weak, unspecified)",
}


def sha256_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def markdown_hashes(markdown: str) -> dict:
    """Hash independently owned regions of a portable Markdown asset.

    Split on an exact sentinel, rejecting missing/ambiguous ownership. Author
    hash excludes machine changes; full-file hash includes both regions.
    """
    if markdown.count(OWNERSHIP_SENTINEL) != 1:
        raise ValueError("expected exactly one ownership sentinel")
    human, machine = markdown.split(OWNERSHIP_SENTINEL, 1)
    return {
        "author_hash": sha256_text(human),
        "machine_hash": sha256_text(machine),
        "file_hash": sha256_text(markdown),
    }


def merge_markdown_enrichment(
    markdown: str, machine_text: str, expected_author_hash: str,
    last_enriched_author_hash: str | None = None,
) -> str:
    """Create a replacement asset while preserving human-authored bytes.

    The caller must compare the returned body before writing it to storage.
    A persistent baseline, *not* the updated file hash, controls re-enrichment.
    """
    hashes = markdown_hashes(markdown)
    if hashes["author_hash"] != expected_author_hash:
        raise ValueError("author text changed since enrichment started")
    if last_enriched_author_hash == hashes["author_hash"]:
        raise ValueError("author text unchanged; self-enrichment prevented")
    if not isinstance(machine_text, str) or len(machine_text) > 16_000:
        raise ValueError("invalid machine enrichment")
    human, _old_machine = markdown.split(OWNERSHIP_SENTINEL, 1)
    return human + OWNERSHIP_SENTINEL + ENRICHMENT_HEADING + machine_text.rstrip("\n") + "\n"


def projection_node(n: dict) -> dict:
    """Shared JSON-stable mapping for bounded MCP and paged Ladybug projections."""
    return {
        "id": n["id"],
        "title": n["title"],
        "kind": n["kind"],
        "status": n.get("status", "current"),
        "source": n.get("source", ""),
        "recorded_at": n.get("recorded_at", n.get("created")),
        "epistemic_status": n.get("epistemic_status", "unreviewed"),
        "intent": n.get("intent", ""),
        "evidence_ref": n.get("evidence_ref", ""),
        "evidence_verified": False,
    }


def projection_edge(snapshot, key: tuple[str, str, str]) -> dict:
    """Preserve directed relation, edge qualifiers, and absent proof of truth."""
    src, dst, rel = key
    return {
        "from": src,
        "to": dst,
        "relation": rel,
        "recorded_at": snapshot.links[key],
        "qualifiers": getattr(snapshot, "link_attributes", {}).get(key, {}),
        "evidence_verified": False,
    }


def project_snapshot(snapshot, limit: int = 200) -> dict:
    """Bounded read-only, plaintext-in-memory graph projection.

    A consumer may import this into another database (e.g. LadybugDB) by
    explicit operator action. Never silently write plaintext graph files.
    """
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")
    active = sorted(
        (node for node in snapshot.nodes.values() if not node.get("archived")),
        key=lambda node: node["id"],
    )
    selected = active[:limit]
    ids = {node["id"] for node in selected}
    nodes = [projection_node(n) for n in selected]
    edges = [
        projection_edge(snapshot, key)
        for key in sorted(snapshot.links)
        if key[0] in ids and key[1] in ids
    ]
    payload = {"nodes": nodes, "links": edges}
    projection_hash = sha256_text(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ))
    return {
        **payload,
        "journal_seq": snapshot.seq,
        "journal_digest": snapshot.digest.hex(),
        "projection_hash": projection_hash,
        "truncated": len(active) > len(selected),
        "projection_is_authoritative": False,
    }
