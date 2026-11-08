"""Standalone encrypted, mirrored event journal for Noosphere Lite.

This module does not parse or import any private Noosphere format.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"NLV1\n"
AAD = b"Noosphere-Lite-MCP/v1:"
MAX_FRAME = 1_048_576
MAX_BODY = 65_536
MAX_EVENTS = 150_000

# Internal capability only passed by the trusted package's own writers.
# Not a sandbox for arbitrary Python code: this is an MCP tool input boundary.
_INTERNAL_WRITER = object()


class VaultError(RuntimeError):
    pass


@dataclass
class Snapshot:
    nodes: dict
    links: dict
    digests: list[bytes]
    digest: bytes
    seq: int


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_instant(value: str | None) -> str | None:
    """Normalize ISO 8601 instants to UTC; never infer dates or timezones."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise VaultError("timestamp must be a nonempty offset-aware ISO 8601 string")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VaultError("invalid ISO 8601 timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise VaultError("timestamp needs an explicit timezone/UTC offset")
    return stamp.astimezone(timezone.utc).isoformat()


def _bounds(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    start, end = _utc_instant(start), _utc_instant(end)
    if start and end and datetime.fromisoformat(end) <= datetime.fromisoformat(start):
        raise VaultError("valid_to must be later than valid_from")
    return start, end


def _words(value: str) -> set[str]:
    return set(re.findall(r"\w{2,}", value.casefold(), re.UNICODE))


def _private_dir(path: Path) -> None:
    if path.is_symlink():
        raise VaultError("symlink directory not allowed")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_mode & 0o077:
        raise VaultError(f"directory has unsafe permissions: {path}")


def _regular_private(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise VaultError(f"not a regular file: {path}")
    if path.stat().st_mode & 0o077:
        raise VaultError(f"file permissions must be owner-only: {path}")


def _read_secure(path: Path) -> bytes:
    _regular_private(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as f:
            return f.read()
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".nlv-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class MemoryVault:
    """Single-writer, local only. On disk: AES-GCM sealed journal, not a graph DB."""

    def __init__(self, primary: str | Path, mirror: str | Path,
                 key_file: str | Path, *, allow_same_device: bool = False):
        self.primary = Path(primary).expanduser().absolute()
        self.mirror = Path(mirror).expanduser().absolute()
        self.key_file = Path(key_file).expanduser().absolute()
        self.allow_same_device = allow_same_device
        if self.primary == self.mirror:
            raise VaultError("primary and mirror must differ")
        for root in (self.primary, self.mirror):
            if self.key_file == root or root in self.key_file.parents:
                raise VaultError("encryption key must be outside data vaults")

    def _check_layout(self) -> None:
        for root in (self.primary, self.mirror):
            if not root.is_dir() or root.is_symlink():
                raise VaultError(f"vault directory missing or symlink: {root}")
            if root.stat().st_mode & 0o077:
                raise VaultError(f"unsafe vault permissions: {root}")
        if not self.allow_same_device and self.primary.stat().st_dev == self.mirror.stat().st_dev:
            raise VaultError("mirrors must be on different filesystems; use explicit DEV override only for testing")

    def initialize(self) -> None:
        if any((root / "journal.nlv").exists() for root in (self.primary, self.mirror)):
            raise VaultError("vault already initialized; refusing to overwrite")
        _private_dir(self.primary)
        _private_dir(self.mirror)
        self._check_layout()
        _private_dir(self.key_file.parent)
        if self.key_file.exists():
            _regular_private(self.key_file)
            if len(_read_secure(self.key_file)) != 32:
                raise VaultError("key file must contain exactly 32 random bytes")
        else:
            fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(secrets.token_bytes(32))
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                _fsync_dir(self.key_file.parent)
        for root in (self.primary, self.mirror):
            _atomic_write(root / "journal.nlv", MAGIC)

    def _key(self) -> bytes:
        self._check_layout()
        key = _read_secure(self.key_file)
        if len(key) != 32:
            raise VaultError("key must be 32 bytes")
        return key

    @contextmanager
    def _lock(self):
        self._check_layout()
        path = self.primary / ".lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                raise VaultError("unsafe lock permissions")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _apply(nodes: dict, links: dict, event: dict):
        op = event.get("op")
        if op == "put":
            data = event["node"]
            nodes[data["id"]] = data
        elif op == "link":
            key = (event["from"], event["to"], event["relation"])
            links[key] = event.get("at")
        elif op == "unlink":
            links.pop((event["from"], event["to"], event["relation"]), None)
        elif op == "archive":
            if event["id"] in nodes:
                nodes[event["id"]] = {**nodes[event["id"]], "archived": True,
                                      "archived_at": event.get("at")}
        elif op == "mark_stale":
            for memory_id in event["ids"]:
                if memory_id in nodes:
                    nodes[memory_id] = {
                        **nodes[memory_id], "status": "stale",
                        "stale_reason": event["reason"], "stale_at": event["at"]
                    }
        elif op == "revise":
            data = event["node"]
            if data["id"] not in nodes:
                raise VaultError("revised memory does not exist")
            nodes[data["id"]] = data
            for memory_id in event["stale_ids"]:
                if memory_id in nodes:
                    nodes[memory_id] = {
                        **nodes[memory_id], "status": "stale",
                        "stale_reason": "Upstream memory revised",
                        "stale_at": event["at"]
                    }
        else:
            raise VaultError("unrecognized journal event")

    def _decode(self, raw: bytes, key: bytes) -> Snapshot:
        if not raw.startswith(MAGIC):
            raise VaultError("unsupported or invalid journal header")
        nodes, links, digests = {}, {}, []
        digest = bytes(32)
        at = len(MAGIC)
        seq = 0
        aes = AESGCM(key)
        while at < len(raw):
            if seq >= MAX_EVENTS or len(raw) - at < 4:
                raise VaultError("journal too large or truncated")
            length = struct.unpack(">I", raw[at:at+4])[0]
            if length < 29 or length > MAX_FRAME or at + 4 + length > len(raw):
                raise VaultError("invalid or incomplete frame")
            frame = raw[at:at+4+length]
            nonce = raw[at+4:at+16]
            ciphertext = raw[at+16:at+4+length]
            try:
                payload = aes.decrypt(nonce, ciphertext,
                                      AAD + (seq+1).to_bytes(8, "big") + digest)
                event = json.loads(payload)
                if not isinstance(event, dict):
                    raise ValueError("event must be a dictionary")
                self._apply(nodes, links, event)
            except Exception as e:
                raise VaultError(f"journal integrity/format failure at event {seq+1}") from e
            digest = hashlib.sha256(digest + frame).digest()
            digests.append(digest)
            seq += 1
            at += len(frame)
        return Snapshot(nodes, links, digests, digest, seq)

    def _reconcile(self, key: bytes) -> Snapshot:
        readings = []
        for root in (self.primary, self.mirror):
            path = root / "journal.nlv"
            try:
                raw = _read_secure(path)
                readings.append((raw, self._decode(raw, key)))
            except (OSError, VaultError):
                readings.append(None)
        if readings == [None, None]:
            raise VaultError("both encrypted copies unavailable or invalid")
        valid = [x for x in readings if x is not None]
        chosen = max(valid, key=lambda pair: pair[1].seq)
        for x in valid:
            prefix = min(x[1].seq, chosen[1].seq)
            if x[1].digests[:prefix] != chosen[1].digests[:prefix]:
                raise VaultError("mirrors diverged; refusing automatic data loss")
        for root, x in zip((self.primary, self.mirror), readings):
            if x is None or x[0] != chosen[0]:
                _atomic_write(root / "journal.nlv", chosen[0])
        return chosen[1]

    def _append(self, event) -> None:
        with self._lock():
            key = self._key()
            state = self._reconcile(key)
            if state.seq >= MAX_EVENTS:
                raise VaultError("maximum event count reached")
            if callable(event):
                event = event(state)
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
            if len(payload) > MAX_BODY:
                raise VaultError("event too large")
            if event["op"] in ("link", "unlink"):
                if event["from"] not in state.nodes or event["to"] not in state.nodes:
                    raise VaultError("relationship points to missing memory")
            nonce = secrets.token_bytes(12)
            ct = AESGCM(key).encrypt(nonce, payload,
                    AAD + (state.seq+1).to_bytes(8, "big") + state.digest)
            frame = struct.pack(">I", len(nonce) + len(ct)) + nonce + ct
            for root in (self.primary, self.mirror):
                path = root / "journal.nlv"
                fd = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
                try:
                    with os.fdopen(fd, "ab") as f:
                        f.write(frame)
                        f.flush()
                        os.fsync(f.fileno())
                except BaseException:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise

    def _snapshot(self) -> Snapshot:
        with self._lock():
            return self._reconcile(self._key())

    def add(self, title: str, body: str, tags: list[str] | None = None,
            kind: str = "note", source: str = "", *,
            valid_from: str | None = None, valid_to: str | None = None,
            observed_at: str | None = None,
            _internal_writer: object | None = None) -> dict:
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 32:
            raise VaultError("invalid memory kind")
        if (kind.startswith("evidence_") or kind == "git_anchor") and _internal_writer is not _INTERNAL_WRITER:
            raise VaultError("reserved system memory kinds require trusted package writer")
        if not 1 <= len(title.strip()) <= 256 or len(body) > 48_000:
            raise VaultError("invalid title/body size")
        tags = tags or []
        if len(tags) > 32 or any(len(x) > 64 for x in tags):
            raise VaultError("invalid tags")
        start, end = _bounds(valid_from, valid_to)
        observed = _utc_instant(observed_at)
        when = _stamp()
        node = dict(id=uuid.uuid4().hex, title=title.strip(), body=body,
                    tags=tags, kind=kind[:32], source=source[:500],
                    created=when, updated=when, recorded_at=when,
                    observed_at=observed, valid_from=start, valid_to=end,
                    archived=False, status="current")
        self._append(dict(op="put", node=node))
        return dict(id=node["id"], title=node["title"], created=when)

    def read(self, memory_id: str) -> dict:
        state = self._snapshot()
        node = state.nodes.get(memory_id)
        if not node or node.get("archived"):
            raise VaultError("memory not found")
        return dict(node)

    def search(self, query: str, limit: int = 10,
               as_of: str | None = None, *,
               _snapshot: Snapshot | None = None) -> list[dict]:
        if not 1 <= len(query.strip()) <= 300:
            raise VaultError("query length must be 1..300")
        moment = _utc_instant(as_of)
        moment_dt = datetime.fromisoformat(moment) if moment else None
        terms = _words(query)
        needle = query.casefold().strip()
        scored = []
        state = _snapshot if _snapshot is not None else self._snapshot()
        for node in state.nodes.values():
            if node.get("archived"):
                continue
            # Evidence claims and retractions must never bypass the evidence gate.
            if str(node.get("kind", "")).startswith("evidence_") or node.get("kind") == "git_anchor":
                continue
            if moment is not None:
                start, end = node.get("valid_from"), node.get("valid_to")
                # Unknown historical validity must not be presented as proven.
                if start is None and end is None:
                    continue
                if start is not None and moment_dt < datetime.fromisoformat(start):
                    continue
                if end is not None and moment_dt >= datetime.fromisoformat(end):
                    continue
            title = node["title"].casefold()
            tags = " ".join(node["tags"]).casefold()
            body = node["body"].casefold()
            score = 10 * (needle in title) + 5 * (needle in tags) + 3 * (needle in body)
            score += 5 * len(terms & _words(title))
            score += 3 * len(terms & _words(tags))
            score += len(terms & _words(body))
            if score:
                scored.append((score, node))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        return [dict(id=n["id"], title=n["title"], tags=n["tags"], kind=n["kind"],
                     snippet=n["body"][:220], status=n.get("status", "current"),
                     recorded_at=n.get("recorded_at", n.get("created")),
                     valid_from=n.get("valid_from"), valid_to=n.get("valid_to"),
                     score=s) for s,n in scored[:max(1, min(limit,50))]]

    def suggest_links(self, memory_id: str, limit: int = 10) -> list[dict]:
        """Read-only hypotheses only; never create a graph edge or assert truth."""
        from .discovery import suggest_links
        snap = self._snapshot()
        try:
            return suggest_links(snap.nodes, snap.links, memory_id, limit)
        except (KeyError, ValueError, TypeError) as exc:
            raise VaultError("invalid or missing memory for link suggestions") from exc

    def link(self, from_id: str, to_id: str, relation: str = "related") -> dict:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", relation):
            raise VaultError("invalid relation")
        self._append(dict(op="link", at=_stamp(),
                          **{"from":from_id, "to":to_id, "relation":relation}))
        return {"linked": True, "from": from_id, "to": to_id, "relation": relation}

    def unlink(self, from_id: str, to_id: str, relation: str = "related") -> dict:
        self._append(dict(op="unlink", at=_stamp(),
                          **{"from":from_id, "to":to_id, "relation":relation}))
        return {"unlinked": True}

    def neighbors(self, memory_id: str, depth: int = 1, limit: int = 100) -> dict:
        state = self._snapshot()
        if memory_id not in state.nodes or state.nodes[memory_id].get("archived"):
            raise VaultError("memory not found")
        discovered, queue, edges = {memory_id}, [(memory_id, 0)], []
        for n, distance in queue:
            if distance >= max(1, min(depth, 3)):
                continue
            for a, b, rel in state.links:
                if a != n and b != n:
                    continue
                neighbor = b if a == n else a
                if state.nodes.get(neighbor, {}).get("archived"):
                    continue
                edges.append({"from": a, "to": b, "relation": rel,
                              "recorded_at": state.links[(a, b, rel)]})
                if neighbor not in discovered and len(discovered) < max(1, min(limit, 200)):
                    discovered.add(neighbor)
                    queue.append((neighbor, distance+1))
            if len(edges) >= max(1, min(limit,200)) * 4:
                break
        nodes = [dict(id=i, title=state.nodes[i]["title"],
                      kind=state.nodes[i]["kind"],
                      status=state.nodes[i].get("status", "current")) for i in discovered]
        return {"nodes": nodes, "links": edges[:800]}

    def context(self, query: str, max_chars: int = 10_000) -> dict:
        state = self._snapshot()
        results = self.search(query, 16, _snapshot=state)
        budget = max(500, min(max_chars, 40_000))
        selected = []
        for hit in results:
            node = dict(state.nodes[hit["id"]])
            size = len(node["body"]) + len(node["title"]) + 200
            if size > budget:
                if not selected:
                    node["body"] = node["body"][:max(0, budget-200)]
                    selected.append(node)
                break
            selected.append(node)
            budget -= size
        return {"query": query, "memories": selected,
                "needs_review": sum(m.get("status") == "stale" for m in selected),
                "truncated": len(selected) < len(results)}

    @staticmethod
    def _downstream(state: Snapshot, origin: str) -> list[str]:
        """Transitively follow child --derived_from--> parent dependencies."""
        reverse = {}
        for child, parent, relation in state.links:
            if relation == "derived_from":
                reverse.setdefault(parent, set()).add(child)
        seen = {origin}
        queue = [origin]
        for parent in queue:
            for child in sorted(reverse.get(parent, ())):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        seen.discard(origin)
        return sorted(seen)

    def invalidate(self, memory_id: str, reason: str = "Source no longer verified") -> dict:
        """Mark this memory and all of its derived descendants stale. Never delete history."""
        if not 1 <= len(reason.strip()) <= 512:
            raise VaultError("reason must be 1..512 characters")
        result = {}
        def make_event(state: Snapshot) -> dict:
            if memory_id not in state.nodes or state.nodes[memory_id].get("archived"):
                raise VaultError("memory not found")
            ids = [memory_id] + self._downstream(state, memory_id)
            result["stale_ids"] = ids
            return {"op": "mark_stale", "ids": ids, "reason": reason.strip(), "at": _stamp()}
        self._append(make_event)
        return {"stale_count": len(result["stale_ids"]), **result}

    def revise(self, memory_id: str, body: str, title: str | None = None,
               *, valid_from: str | None = None,
               valid_to: str | None = None) -> dict:
        """Update a source record and automatically stale downstream derived memories."""
        if not isinstance(body, str) or len(body) > 48_000:
            raise VaultError("invalid body")
        if title is not None and (not isinstance(title, str) or not 1 <= len(title.strip()) <= 256):
            raise VaultError("invalid title")
        result = {}
        def make_event(state: Snapshot) -> dict:
            old = state.nodes.get(memory_id)
            if not old or old.get("archived"):
                raise VaultError("memory not found")
            if old.get("kind") in ("evidence_claim", "evidence_tombstone"):
                raise VaultError("evidence claims and rejection tombstones are immutable")
            at = _stamp()
            updated = dict(old, body=body, updated=at, status="current")
            if valid_from is not None or valid_to is not None:
                start = valid_from if valid_from is not None else old.get("valid_from")
                end = valid_to if valid_to is not None else old.get("valid_to")
                updated["valid_from"], updated["valid_to"] = _bounds(start, end)
            updated.pop("stale_reason", None)
            updated.pop("stale_at", None)
            if title is not None:
                updated["title"] = title.strip()
            stale_ids = self._downstream(state, memory_id)
            result.update({"id": memory_id, "updated": at, "downstream_stale": len(stale_ids)})
            return {"op": "revise", "node": updated,
                    "stale_ids": stale_ids, "at": at}
        self._append(make_event)
        return result

    def archive(self, memory_id: str) -> dict:
        node = self.read(memory_id)
        if node.get("kind") == "evidence_tombstone":
            raise VaultError("rejection tombstones cannot be archived")
        self._append(dict(op="archive", id=memory_id, at=_stamp()))
        return {"archived": True, "warning": "archived records remain in encrypted event history"}

    def status(self) -> dict:
        snap = self._snapshot()
        return {"memories": sum(not x.get("archived",False) for x in snap.nodes.values()),
                "relationships": len(snap.links), "events": snap.seq,
                "encrypted": True, "mirrors_valid": True,
                "distinct_filesystems": self.primary.stat().st_dev != self.mirror.stat().st_dev}

