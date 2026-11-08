# Git-aware memory / drift veto R03 (2026-11-08)

Git tracked-file identity is linked to the origin of a memory, rather than substituting for semantic verification. The Linux-native Lite MCP service can flag a memory and its derived descendants for review when its tracked code changes. Git content comparison is **not** a proof of a claim's truth.

## Operator setup

Configure only explicitly approved local worktrees using environment variable `NSL_GIT_ROOTS_JSON` (JSON object alias → absolute existing worktree root, e.g. `{"project":"/home/user/projects/project"}`). A client cannot request a new Git root. With no configured roots (default), checks fail closed for Git-anchored facts and ordinary memory tools continue to work. Access to the configured paths is granted to the local MCP server process, not by a note's text. **Do not expose stdio tools to untrusted clients without authorization.**

## New MCP tools

- `memory_git_anchor(memory_id, repo_alias, relative_path)`: register a clean, committed file's HEAD Git blob and observed commit in the encrypted mirrored journal, link the memory by `derived_from`, preserve the recorded time. Refuses symlinks, traversal, untracked files and dirty worktrees.
- `memory_git_status(memory_id)`: reevaluate anchored file hashes at read time; returns `current`, `stale_needs_review` or `unanchored` (never proof of truth).
- `memory_git_scan(invalidate_stale=false, limit=100)`: inspect linked anchors and return drift. With explicit `invalidate_stale=true`, cascade stale status through derived descendants without destroying journal history. Reversing a file change never automatically un-stales a previously invalidated memory.

Regular `memory_search` explicitly reports `git_provenance`; ordinary `memory_context` suppresses drifted Git-bound memories when using the guarded MCP adapter and reports their count. Strict evidence retrieval calls `EvidenceGate`'s live Git validator for every `git_anchor` dependency and withholds claims even if background scanning has never run. Existing legacy notes without Git anchors remain explicitly **unreviewed**, not proven. Entries of kind `git_anchor` are excluded from generic search.

## Limits and security

This implementation detects drift in **locally configured Git worktrees**, both committed HEAD blob and uncommitted worktree bytes. It does not fetch remotes, resolve dependency semantics automatically, run external code, or watch GitHub commits not checked out locally. Renames show as missing/stale until reviewed. No automated LLM approval or semantic self-certification; an operator must decide whether a code change invalidates the asserted behavior. Existing encrypted journal format is unchanged.

`PYTHONPATH=. python3 -m unittest discover -s tests -q` includes tests for clean anchors, unrelated commits, changed tracked code, dirty worktrees, rejected paths and symlinks, strict evidence veto, irreversible stale cascade and missing config.
