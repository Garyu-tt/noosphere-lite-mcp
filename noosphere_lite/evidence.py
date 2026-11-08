"""Evidence-first read path for Noosphere Lite.

All evidence sources, candidate claims and rejection tombstones are stored in the
existing encrypted, mirrored MemoryVault journal. This is NOT a truth oracle:
exact equality to source JSON proves a quoted observation, not external truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from .vault import MemoryVault, VaultError, _utc_instant, _INTERNAL_WRITER

_KEY = re.compile(r"[a-zA-Z0-9_.:-]{1,120}\Z")
_SCOPE = re.compile(r"[a-zA-Z0-9_.:-]{1,48}\Z")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _pointer(obj, path: str):
    if not isinstance(path, str) or len(path) > 300 or (path and not path.startswith("/")):
        raise VaultError("invalid JSON pointer")
    parts = [] if not path else path[1:].split("/")
    if len(parts) > 12:
        raise VaultError("JSON pointer depth exceeded")
    for part in parts:
        if re.search(r"~(?![01])", part):
            raise VaultError("invalid JSON pointer escape")
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(obj, dict):
            if part not in obj:
                raise VaultError("source pointer missing")
            obj = obj[part]
        elif isinstance(obj, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            index = int(part)
            if index >= len(obj):
                raise VaultError("source pointer missing")
            obj = obj[index]
        else:
            raise VaultError("source pointer missing")
    return obj


class EvidenceGate:
    """Fail-closed read view; scope is an organizational filter, NOT an ACL.

    MCP stdio transport is local. Never expose this to untrusted clients without
    authenticated authorization; no public claim approval endpoint is provided.
    """

    def __init__(self, vault: MemoryVault, git_guard=None):
        self.vault = vault
        self.git_guard = git_guard

    def add_source(self, title: str, json_document: str, *,
                   observed_at: str | None = None, scope: str = "default") -> dict:
        if not _SCOPE.fullmatch(scope):
            raise VaultError("invalid scope")
        if not isinstance(json_document, str) or not 1 <= len(json_document.encode("utf-8")) <= 40_000:
            raise VaultError("JSON source must be 1..40000 bytes")
        try:
            obj = json.loads(json_document)
            normalized = _canonical(obj)
        except (ValueError, TypeError) as exc:
            raise VaultError("invalid JSON evidence source") from exc
        result = self.vault.add(title, normalized, kind="evidence_source",
                                tags=["evidence", scope], observed_at=observed_at,
                                _internal_writer=_INTERNAL_WRITER)
        return {**result, "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest()}

    def propose(self, fact_key: str, source_id: str, pointer: str, *,
                scope: str = "default", author: str = "unreviewed",
                valid_from: str | None = None, valid_to: str | None = None,
                stale_after: str | None = None) -> dict:
        if not _KEY.fullmatch(fact_key) or not _SCOPE.fullmatch(scope):
            raise VaultError("invalid fact key or scope")
        if not isinstance(author, str) or not 1 <= len(author) <= 120:
            raise VaultError("invalid author")
        stale_after = _utc_instant(stale_after)
        source = self.vault.read(source_id)
        if source["kind"] != "evidence_source" or source.get("status") != "current":
            raise VaultError("source is not active evidence")
        try:
            value = _pointer(json.loads(source["body"]), pointer)
            digest = _digest(value)
        except (ValueError, TypeError) as exc:
            raise VaultError("source is not valid JSON") from exc
        snapshot = self.vault._snapshot()
        for n in snapshot.nodes.values():
            if n.get("kind") != "evidence_tombstone":
                continue
            try:
                tomb = json.loads(n["body"])
            except (ValueError, KeyError, TypeError):
                continue
            if (tomb.get("scope"), tomb.get("fact_key"), tomb.get("value_digest")) == (scope, fact_key, digest):
                raise VaultError("previously rejected value cannot be reintroduced")
        claim = dict(schema=1, fact_key=fact_key, scope=scope, value=value,
                     value_digest=digest, pointer=pointer, source_id=source_id,
                     source_sha256=hashlib.sha256(source["body"].encode("utf-8")).hexdigest(),
                     author=author, review_state="source_matched_unreviewed",
                     stale_after=stale_after, publication_approved=False)
        result = self.vault.add(fact_key, _canonical(claim), kind="evidence_claim",
                                tags=["evidence", scope], valid_from=valid_from,
                                valid_to=valid_to,
                                _internal_writer=_INTERNAL_WRITER)
        self.vault.link(result["id"], source_id, "derived_from")
        return {**result, "status": "source_matched_unreviewed",
                "warning": "matching source bytes does not establish real-world truth"}

    def reject(self, claim_id: str, reason: str) -> dict:
        node = self.vault.read(claim_id)
        if node.get("kind") != "evidence_claim":
            raise VaultError("not an evidence claim")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            raise VaultError("reason must be 1..500 characters")
        try:
            claim = json.loads(node["body"])
            if claim["value_digest"] != _digest(claim["value"]):
                raise VaultError("claim integrity failed")
        except (KeyError, ValueError, TypeError) as exc:
            raise VaultError("malformed claim") from exc
        tomb = dict(schema=1, scope=claim["scope"], fact_key=claim["fact_key"],
                    value_digest=claim["value_digest"], reason=reason.strip(),
                    rejected_claim_id=claim_id)
        # Write the durable tombstone FIRST. If invalidation fails, reads still
        # exclude the rejected value; no false resurrection after interruption.
        item = self.vault.add("Rejected: " + claim["fact_key"], _canonical(tomb),
                              kind="evidence_tombstone", tags=["evidence", claim["scope"]],
                              _internal_writer=_INTERNAL_WRITER)
        self.vault.invalidate(claim_id, reason.strip())
        return {"rejected": True, "tombstone_id": item["id"]}

    def query(self, question: str = "", *, scope: str = "default",
              as_of: str | None = None, limit: int = 20) -> dict:
        if not _SCOPE.fullmatch(scope):
            raise VaultError("invalid scope")
        moment = _utc_instant(as_of) if as_of is not None else None
        when = datetime.fromisoformat(moment) if moment else datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        if not isinstance(question, str) or len(question) > 300:
            raise VaultError("query too long")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise VaultError("limit must be 1..50")
        snap = self.vault._snapshot()
        tombstones = set()
        for node in snap.nodes.values():
            if node.get("kind") == "evidence_tombstone":
                try:
                    data = json.loads(node["body"])
                    tombstones.add((data["scope"], data["fact_key"], data["value_digest"]))
                except (TypeError, ValueError, KeyError):
                    continue
        matches, rejected = [], {}
        def discard(reason):
            rejected[reason] = rejected.get(reason, 0) + 1
        q = question.casefold().strip()
        dependencies = {}
        for child, parent, relation in snap.links:
            if relation == "derived_from":
                dependencies.setdefault(child, set()).add(parent)

        def sound_dependencies(claim_id):
            seen, queue = set(), [claim_id]
            while queue:
                child = queue.pop()
                if child in seen:
                    continue
                seen.add(child)
                for parent in dependencies.get(child, ()):
                    node = snap.nodes.get(parent)
                    if not node or node.get("archived") or node.get("status") != "current":
                        return False
                    # Git-linked evidence must validate against the live local
                    # worktree every time, even before any scheduled scan.
                    if node.get("kind") == "git_anchor":
                        if (self.git_guard is None or
                                self.git_guard.inspect_anchor(node).get("status") != "current"):
                            return False
                    queue.append(parent)
            return True

        for claim_id, node in snap.nodes.items():
            if node.get("kind") != "evidence_claim":
                continue
            try:
                c = json.loads(node["body"])
                if c["scope"] != scope:
                    continue
                if q and q not in c["fact_key"].casefold() and q not in _canonical(c["value"]).casefold():
                    continue
                if node.get("archived") or node.get("status") != "current":
                    discard("not_current")
                    continue
                if (scope, c["fact_key"], c["value_digest"]) in tombstones:
                    discard("rejected_value")
                    continue
                if c.get("review_state") != "source_matched_unreviewed" or c.get("publication_approved") is not False:
                    discard("unsafe_review_state")
                    continue
                if not sound_dependencies(claim_id):
                    discard("stale_dependency")
                    continue
                begin = node.get("valid_from")
                end = node.get("valid_to")
                if moment and not begin and not end:
                    discard("unknown_historical_validity")
                    continue
                if begin and when < datetime.fromisoformat(_utc_instant(begin)):
                    continue
                if end and when >= datetime.fromisoformat(_utc_instant(end)):
                    continue
                expired = c.get("stale_after")
                if expired and now >= datetime.fromisoformat(_utc_instant(expired)):
                    discard("expired")
                    continue
                source = snap.nodes.get(c["source_id"])
                if (not source or source.get("kind") != "evidence_source"
                        or source.get("archived") or source.get("status") != "current"
                        or c["source_id"] not in dependencies.get(claim_id, ())):
                    discard("missing_or_stale_source")
                    continue
                if hashlib.sha256(source["body"].encode("utf-8")).hexdigest() != c["source_sha256"]:
                    discard("source_changed")
                    continue
                observed = _pointer(json.loads(source["body"]), c["pointer"])
                if type(observed) is not type(c["value"]) or observed != c["value"] or _digest(observed) != c["value_digest"]:
                    discard("value_disagrees_with_source")
                    continue
                matches.append(dict(fact_key=c["fact_key"], scope=scope, value=observed,
                                    pointer=c["pointer"], source_id=c["source_id"],
                                    source_sha256=c["source_sha256"], claim_id=claim_id,
                                    recorded_at=node["recorded_at"],
                                    valid_from=begin, valid_to=end,
                                    review_state="source_matched_unreviewed",
                                    truth_guaranteed=False))
            except (KeyError, TypeError, ValueError, OverflowError, VaultError):
                discard("malformed_or_unverifiable")
        # Two different values for one key at the same time are a conflict,
        # never a reason to silently prefer the newest or most repeated.
        values = {}
        for item in matches:
            values.setdefault(item["fact_key"], set()).add(_digest(item["value"]))
        conflicts = sorted(k for k, v in values.items() if len(v) > 1)
        matches = [x for x in matches if x["fact_key"] not in conflicts]
        matches.sort(key=lambda x: (x["fact_key"], x["claim_id"]))
        return {"status": "conflict" if conflicts else ("source_matched_only" if matches else "insufficient_evidence"),
                "facts": matches[:limit], "conflicts": conflicts, "rejected": rejected,
                "truncated": len(matches) > limit,
                "warning": "Source JSON equality is not external verification; review before relying on consequential claims."}
