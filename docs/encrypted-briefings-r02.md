# Encrypted project briefing + source cards (R02, 2026-11-08)

Noosphere Lite's encrypted journal already stores ordinary notes and source-matched evidence; this extension adds **two read-only MCP tools** that can reconstruct project-specific working context without a separate plaintext SQLite memory cache.

The module is `noosphere_lite/briefing.py`. Both views read the existing `MemoryVault` AES-256-GCM mirrored journal in memory, do not write new durable metadata, do not read source files from the host, do not infer relationships and do not approve any claims.

## 1. memory_briefing

Call `memory_briefing(project="my-app", limit=20)` to get a structured cross-session briefing:

- current rules: kinds `negative` then `invariant`;
- open work: `open_loop`;
- durable choices: `decision`;
- ordinary scoped `fact` notes;
- records marked `stale` or with unknown historical validity in a separate `review_required` list, not treated as active instructions;
- source-matched JSON observations from the existing `EvidenceGate` under that same scope, labelled `source_matched_unreviewed`;
- evidence conflicts (if there are multiple incompatible values for a key) rather than silently choosing the newest result.

To create a matching regular note, call the existing MCP tool with:

    memory_add(
        title="Do not modify the encryption key",
        body="Changes to key storage require a reviewed migration and backups.",
        tags=["project:my-app"],
        kind="negative",
        source="docs/key-rotation.md"
    )

Use `memory_briefing(project="my-app", at="2026-01-01T00:00:00Z")` only when known validity times were explicitly recorded. Unknown historical validity is not invented. Ordinary note content remains **unreviewed**, even if its source label appears plausible. Source-matched observations still require human or independent verification.

A future or expired rule is excluded from current active briefing. A stale rule is placed in `review_required`; never automatically treat it as an instruction to execute.

## 2. memory_by_source

Use `memory_by_source(project="my-app", source_ref="src/worker.py")` to return only registered project cards whose `source` field exactly matches the requested string. This follows the deterministic path-addressing idea: given a file, the agent can locate related constraints without semantic retrieval.

The match is strictly literal and **does not read or inspect** `src/worker.py`. The source label is not proof that the code exists, that its hash is current, or that the note is true. It reports `needs_review` for stale cards. Consumers who need proof must inspect the actual source and use trusted evidence procedures separately.

## Safety and operational boundaries

- Project tags and EvidenceGate scope are **organizational selectors, not ACLs or multi-tenant authorization**. Only give the local stdio MCP interface to trusted agents.
- No plaintext index, background watcher, filesystem source scan, network endpoint or host-process execution was added.
- Only explicitly typed project records are included; general notes and raw `evidence_*` metadata never bypass the EvidenceGate.
- Inputs are validated; output size and record count are bounded. Oversized records are omitted, not silently truncated. Read the record by ID using `memory_read` if authorized.
- The feature does not replace source-version drift checks, fact auditing, repository-level approval or the distinct professional Noosphere forum/control plane.
- This is a new MCP read interface in the public code, not evidence of a deployment into a live/professional instance.

## Regression tests

    python3 -m unittest discover -s tests -v
    python3 -m unittest discover -s examples/memory_synthesis -v

The dedicated tests cover project isolation, rule priority, stale dependency chains, historical windows, unknown validity, evidence conflicts and tombstones, exact source references, read-only filesystem behavior, output bounds, mirror replay and invalid inputs.

## Research attribution

Inspired by the *ideas*, not copied source code, of Agents Remember, Daimon and Primnox. The source-pinned public catalog and license notes are in [research-memory-candidates-2026-11-08.md](research-memory-candidates-2026-11-08.md). Primnox BSL 1.1 code is not vendored. Engram's experimental scoring mechanisms remain unmerged pending comparable benchmarks.
