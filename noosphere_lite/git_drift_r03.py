"""Read-only Git provenance with explicit operator allowlisted worktrees.

Anchors are observations of Git blob identity, not proofs of code semantics.
Only callers that have configured a repository alias can anchor/inspect it.
A changed or unreadable file vetoes dependent evidence, never promotes truth.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from .vault import MemoryVault, VaultError, _INTERNAL_WRITER

ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}\Z")
OBJECT = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")


class GitDriftGuard:
    def __init__(self, vault: MemoryVault, roots: dict[str, str | Path] | None = None):
        self.vault = vault
        self.roots = {}
        for alias, value in (roots or {}).items():
            if not isinstance(alias, str) or not ALIAS.fullmatch(alias):
                raise VaultError("invalid git repository alias")
            raw = Path(value).expanduser()
            if not raw.is_absolute() or raw.is_symlink() or not raw.is_dir():
                raise VaultError("git roots must be existing absolute non-symlink dirs")
            root = raw.resolve(strict=True)
            if root == Path("/") or len(root.parts) < 3:
                raise VaultError("git root too broad")
            self.roots[alias] = root

    @classmethod
    def configured(cls, vault: MemoryVault):
        raw = os.environ.get("NSL_GIT_ROOTS_JSON", "{}")
        try:
            roots = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise VaultError("invalid NSL_GIT_ROOTS_JSON") from exc
        if type(roots) is not dict or len(roots) > 20:
            raise VaultError("git root config must be an object of <=20 aliases")
        return cls(vault, roots)

    @staticmethod
    def _path(value: str):
        if not isinstance(value, str) or not 1 <= len(value) <= 240:
            raise VaultError("invalid repo-relative git path")
        if "\\" in value or "\x00" in value or any(ord(ch) < 32 for ch in value):
            raise VaultError("unsafe git path characters")
        path = PurePosixPath(value)
        if (path.is_absolute() or value.startswith("-") or
                any(part in ("", ".", "..") or part.startswith("-") for part in value.split("/"))):
            raise VaultError("unsafe repo-relative git path")
        return str(path)

    @staticmethod
    def _run(root: Path, *args: str) -> str:
        try:
            proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                  stdin=subprocess.DEVNULL, timeout=5, check=False,
                                  env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1",
                                       "GIT_OPTIONAL_LOCKS": "0",
                                       "GIT_TERMINAL_PROMPT": "0"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VaultError("git unavailable") from exc
        if proc.returncode or len(proc.stdout) > 4096:
            raise VaultError("git revision or path unavailable")
        return proc.stdout.decode("utf-8", errors="strict").strip()

    def _inspect_file(self, alias: str, relative_path: str) -> dict:
        if alias not in self.roots:
            raise VaultError("git repository alias not configured")
        relative_path = self._path(relative_path)
        root = self.roots[alias]
        if Path(self._run(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise VaultError("configured root must be the Git worktree root")
        source = root / relative_path
        if source.resolve(strict=False).is_relative_to(root) is False:
            raise VaultError("git path escapes worktree")
        current = root
        for part in relative_path.split("/"):
            current /= part
            if current.is_symlink():
                raise VaultError("symlink paths are not accepted")
        if not source.is_file():
            raise VaultError("tracked file unavailable")
        commit = self._run(root, "rev-parse", "--verify", "HEAD")
        committed_blob = self._run(root, "rev-parse", "--verify", "HEAD:" + relative_path)
        # The git worktree is read-only here: no user-controlled shell,
        # filters, hooks, network remotes, or git checkout.
        worktree_blob = self._run(root, "hash-object", "--no-filters", "--", relative_path)
        if not all(OBJECT.fullmatch(x) for x in (commit, committed_blob, worktree_blob)):
            raise VaultError("invalid git object ID")
        return dict(commit=commit, committed_blob=committed_blob,
                    worktree_blob=worktree_blob,
                    dirty=committed_blob != worktree_blob)

    def anchor(self, memory_id: str, alias: str, relative_path: str) -> dict:
        node = self.vault.read(memory_id)
        if node.get("kind") in ("git_anchor", "evidence_tombstone"):
            raise VaultError("cannot anchor metadata or rejection tombstones")
        if node.get("status") != "current":
            raise VaultError("cannot anchor stale memory")
        state = self._inspect_file(alias, relative_path)
        if state["dirty"]:
            raise VaultError("must anchor a clean committed file")
        info = dict(schema=1, repo_alias=alias, relative_path=self._path(relative_path),
                    expected_blob=state["committed_blob"],
                    observed_commit=state["commit"], memory_id=memory_id)
        record = self.vault.add("Git anchor " + alias + ":" + relative_path,
                                json.dumps(info, sort_keys=True), kind="git_anchor",
                                _internal_writer=_INTERNAL_WRITER)
        self.vault.link(memory_id, record["id"], "derived_from")
        return {"anchor_id": record["id"], "memory_id": memory_id,
                "repo_alias": alias, "relative_path": relative_path,
                "observed_commit": state["commit"],
                "expected_blob": state["committed_blob"],
                "status": "anchored_unreviewed", "truth_guaranteed": False}

    def inspect_anchor(self, node: dict) -> dict:
        try:
            if (node.get("kind") != "git_anchor" or node.get("archived") or
                    node.get("status") != "current"):
                return {"status": "stale_or_unavailable", "reason": "anchor_inactive"}
            info = json.loads(node["body"])
            if (type(info) is not dict or info.get("schema") != 1 or
                    not OBJECT.fullmatch(info.get("expected_blob", "")) or
                    not OBJECT.fullmatch(info.get("observed_commit", ""))):
                return {"status": "stale_or_unavailable", "reason": "malformed_anchor"}
            actual = self._inspect_file(info["repo_alias"], info["relative_path"])
            stable = (not actual["dirty"] and actual["committed_blob"] == info["expected_blob"])
            return {"status": "current" if stable else "stale",
                    "repo_alias": info["repo_alias"],
                    "relative_path": info["relative_path"],
                    "expected_blob": info["expected_blob"],
                    "current_blob": actual["committed_blob"],
                    "worktree_dirty": actual["dirty"],
                    "observed_commit": info["observed_commit"],
                    "current_commit": actual["commit"],
                    "truth_guaranteed": False}
        except (KeyError, TypeError, ValueError, VaultError, UnicodeError):
            return {"status": "stale_or_unavailable", "reason": "git_provenance_unavailable"}

    def status(self, memory_id: str, *, _snapshot=None) -> dict:
        state = _snapshot if _snapshot is not None else self.vault._snapshot()
        if memory_id not in state.nodes:
            raise VaultError("memory not found")
        items = [self.inspect_anchor(state.nodes[parent]) | {"anchor_id": parent}
                 for child, parent, relation in state.links
                 if child == memory_id and relation == "derived_from"
                 and state.nodes.get(parent, {}).get("kind") == "git_anchor"]
        items.sort(key=lambda x: x["anchor_id"])
        note_inactive = (state.nodes[memory_id].get("status") != "current" or
                         state.nodes[memory_id].get("archived", False))
        return {"memory_id": memory_id,
                "status": ("stale_needs_review" if note_inactive else
                           "unanchored" if not items else
                           "current" if all(x["status"] == "current" for x in items)
                           else "stale_needs_review"),
                "anchors": items, "truth_guaranteed": False}

    def scan(self, invalidate: bool = False, limit: int = 100) -> dict:
        if type(invalidate) is not bool or type(limit) is not int or not 1 <= limit <= 500:
            raise VaultError("invalid Git scan args")
        snap = self.vault._snapshot()
        bound = sorted((child, parent) for (child, parent, relation) in snap.links
                       if relation == "derived_from" and
                       snap.nodes.get(parent, {}).get("kind") == "git_anchor")
        results = []
        for memory_id, anchor_id in bound[:limit]:
            if snap.nodes.get(memory_id, {}).get("archived"):
                continue
            inspection = self.inspect_anchor(snap.nodes[anchor_id])
            if inspection["status"] != "current" and invalidate:
                # Explicit action invalidates anchored memory and its descendants.
                # Never silently regenerate a claim when code changes back.
                if snap.nodes[memory_id].get("status") == "current":
                    self.vault.invalidate(memory_id, "Git drift or unavailable anchored source: " + anchor_id)
            results.append({"memory_id": memory_id, "anchor_id": anchor_id,
                            "status": inspection["status"]})
        return {"results": results, "total_anchors": len(bound),
                "truncated": len(bound) > limit, "invalidation_requested": invalidate,
                "truth_guaranteed": False}
