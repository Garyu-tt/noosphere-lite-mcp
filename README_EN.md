# Noosphere Lite MCP

**Long-term memory for AI agents that does not need to fit inside a context window.**

*By Garyu-tt · v0.3.0 · Linux / Python / MCP · GNU GPLv3*

[Русская документация](README.md)

## What is Noosphere?

Imagine working with an AI agent for weeks. You make decisions, fix problems, build on previous results — and then a new conversation begins and important context has to be explained again.

**Noosphere Lite is long-term memory that lives independently of an agent or chat session.** It stores knowledge, its history and relationships, then delivers the relevant part to an MCP-compatible agent when needed.

It does not make the model's context unlimited. It makes the context a workspace rather than an archive. One agent records a decision, another can retrieve it later and continue from there.

## The ideas that matter

**Memory on demand.** Search returns concise matches. The agent can fetch a single record, inspect neighbors or assemble a bounded context relevant to the task.

**A graph, not a pile of notes.** Memories have titles, content, tags, kinds, timestamps, source references and random IDs. Directed links such as related, supports, blocks and derived_from connect decisions to evidence and other memories. Explore neighborhoods up to three hops.

**Cascading staleness.** Suppose decision C depends on conclusion B, which depends on observation A. If A is revised, B and C are marked stale automatically. If A is invalidated, A, B and C are marked stale. Nothing is quietly deleted. The system signals that downstream claims need rechecking.

    Observation A
        ↑ derived_from
    Conclusion B
        ↑ derived_from
    Decision C

Only explicit derived_from links trigger a cascade. Lite does not yet extract dependency relationships automatically. Current means 'not flagged stale', not 'fact checked'.

**History is preserved.** Changes are appended as authenticated encrypted events. Archiving hides an entry from normal retrieval but does not erase historical encrypted records.

**Storage is encrypted and mirrored.** At rest, Lite uses an AES-256-GCM encrypted binary event journal (NLV1). The working graph is reconstructed transiently in process memory. No plaintext persistent search index is created. Two journals are validated and reconciled, requiring different filesystems by default. An independently secured backup of the key is essential. Mirroring is not a substitute for offline/offsite backups.

**Local-first MCP.** Runs on Linux without a separate model, GPU or cloud service. The stdio MCP server exposes memory tools and does not listen on a public HTTP port, execute shell commands or browse arbitrary host files.

## Install (Python 3.11+)

    git clone https://github.com/Garyu-tt/noosphere-lite-mcp.git
    cd noosphere-lite-mcp
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .

Prepare two independently mounted filesystems, then:

    export NSL_PRIMARY=/mnt/storage-a/noosphere-lite
    export NSL_MIRROR=/mnt/storage-b/noosphere-lite
    export NSL_KEY_FILE="$HOME/.config/noosphere-lite/key"

    python -m noosphere_lite init
    python -m noosphere_lite status
    python -m noosphere_lite mcp

Data directories require 0700 permissions; key and journal files require 0600. Protect the key separately. Losing every key copy loses the memory. A compromised running user/agent session may access the key despite disk encryption.

For **disposable, same-disk tests only**, set NSL_DEVELOPMENT_SAME_DEVICE=1. This disables independent-filesystem enforcement and is not safe redundancy.

Example for stdio-compatible MCP host configuration:

    {
      "mcpServers": {
        "noosphere-lite": {
          "command": "/absolute/path/noosphere-lite-mcp/.venv/bin/python",
          "args": ["-m", "noosphere_lite", "mcp"],
          "env": {
            "NSL_PRIMARY": "/mnt/storage-a/noosphere-lite",
            "NSL_MIRROR": "/mnt/storage-b/noosphere-lite",
            "NSL_KEY_FILE": "/home/you/.config/noosphere-lite/key"
          }
        }
      }
    }

Hosted ChatGPT use may require a separately supported MCP bridge; this local configuration does not itself install a hosted ChatGPT connector.

### Encrypted project briefings and source cards (R02)

The new [memory_briefing and memory_by_source](docs/encrypted-briefings-r02.md) tools read the existing NLV1 AES-GCM journal in memory, **without creating a plaintext search index**. Opt in by tagging notes `project:my-app` and using the `negative`, `invariant`, `open_loop`, `decision` or `fact` kinds. Source-path matching uses exact labels and never reads files or verifies their Git freshness. EvidenceGate separately supplies source-matched, unreviewed observations and conflict flags, not proven facts. Project tags are filters, NOT access controls.


## Eighteen MCP tools

| Tool | Purpose |
| --- | --- |
| memory_add | Store notes, decisions, facts and tasks |
| memory_search | Return compact ranked matches |
| memory_suggest_links | Read-only, unverified lexical link suggestions; never creates edges |
| memory_read | Retrieve one complete memory |
| memory_context | Assemble bounded task context |
| memory_link / memory_unlink | Manage typed links |
| memory_neighborhood | Explore graph neighbors |
| memory_revise | Revise a record and stale derived descendants |
| memory_invalidate | Mark a record and its dependencies stale |
| memory_archive | Hide without destroying encrypted history |
| memory_status | Verify journals and counts |
| memory_evidence_source_add / memory_evidence_propose | Store source JSON and propose an unreviewed, pointer-matched claim |
| memory_evidence_reject / memory_evidence_context | Preserve retractions and read only source-matched candidates with conflict checks |
| memory_briefing | Assemble scoped constraints, open work and source-matched observations from the encrypted journal |
| memory_by_source | Retrieve project notes by exact stored source label, without accessing host files |

## Experimental reviewed graph weights (R04)

The [reviewed_plasticity reference implementation](examples/reviewed_plasticity/README.md) demonstrates sparse link-utility weights, explicit independent QA attribution, SHA-256 evidence checks, idempotent feedback, and rollback. **It is not integrated into Lite MCP 0.3.0 or its encrypted NLV1 journal**, and does not change LLM model parameters. The optional SQLite sidecar is unencrypted and requires an authenticated host-side reviewer workflow before production use.

## Experimental provenance-aware temporal memory (R01)

The independent [memory synthesis example](examples/memory_synthesis/README.md) demonstrates Git/SHA-256 source freshness, source-checked quotations, temporal facts and historical recall, scoped supersession, negative knowledge, session briefs and SQLite FTS5 search. A [dated catalog of 27 research candidates](docs/research-memory-candidates-2026-11-08.md) credits Agents Remember, Daimon, Primnox and Engram and records their license boundaries.

**This is not part of the encrypted Lite 0.3.0 core.** The example uses plaintext SQLite and must not be used with confidential data. Professional forums, internal orchestration and administrative facilities are not included.

## What it does not do yet

Search is lexical, not embeddings or semantic LLM retrieval. Dependencies must be explicitly linked; neither factual truth nor contradictory evidence is automatically verified. Automatic relevance aging, semantic retrieval, conflict resolution, history compaction, per-agent permissions and offsite backup integration are on the roadmap.

This is a single-host, single-writer event journal, **not** a distributed database. Queries replay encrypted journal events, so large deployments require further performance work. The current cap is 150,000 events, not 150,000 graph nodes. Archive is not irreversible data erasure.

Two mirror copies can still be lost together; use independent backup procedures and protect encryption keys.

## Tests

    python -m unittest discover -s tests -v

Tests cover encryption, tamper detection, mirror recovery, graph navigation, and multi-level cascading staleness. Local MCP tool calls have also been smoke-tested with synthetic records.

---

**Noosphere Lite MCP — because a new conversation shouldn't mean starting from scratch.**

*Garyu-tt · GNU GPLv3 · [По-русски](README.md)*


## License / Authorship

Original project code in this release: **GNU GPL-3.0-or-later**. Copyright (C) 2026 [Garyu-tt](https://github.com/Garyu-tt). See [LICENSE](LICENSE) and [AUTHORS.md](AUTHORS.md). Previously published MIT-licensed versions retain their earlier permissions and existing contributors' acknowledgments.


## Experimental candidate link discovery (0.3.0)

The `memory_suggest_links` MCP tool proposes **unverified** possible links using bounded lexical overlap across titles, tags, and text. It never changes the encrypted journal, never claims inferred relations are true, and excludes direct links and archived records. Review source evidence and test applicability before calling `memory_link`. This is **not** semantic vector retrieval, automatic skill transfer, or validated precision/recall.

An exploratory benchmark from the owner's much larger private metagraph is published under `benchmarks/discovery-pilot-2026-11-08/`; **those measurements are not performance figures for Lite**. The benchmark makes the limits explicit and includes a synthetic, privacy-safe regression test.
