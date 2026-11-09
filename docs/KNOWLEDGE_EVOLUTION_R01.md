# Knowledge Evolution R01 — additive truth/meaning separation

Status: tested feature branch (not a production deployment).

This extension borrows *ideas* from:
- [Knowledge Graph Relationships and Enrichment](https://github.com/l00p3rl00p/barely-passable-ai-stuff/blob/main/Knowledge_Graph_Relationships_and_Enrichment.md)
- [Knowledge Asset Evolution Spec v1.6.3](https://github.com/l00p3rl00p/barely-passable-ai-stuff/blob/main/Knowledge-Asset-Evolution-Spec-v1.6.3.md)

The implementation is original to Noosphere Lite; it does not copy those projects'
source code or require adoption of a third-party architecture or graph database.

## What we keep

- Encrypted, mirrored, append-only Noosphere Lite event journal is the **Truth** layer.
- Existing memory, evidence and Git-drift gates remain in charge of verification.
- Graph views and prospective LadybugDB/NetworkX integrations are derived
  **Meaning** projections, never authoritative copies.
- Learning/model optimization is a separate concern. Neither an LLM's assertion
  nor a graph edge automatically becomes verified evidence.

## New MCP operations

- `memory_enrichment_gate(memory_id)` returns a SHA-256 hash of the author-owned
  memory body, the last enriched baseline, and `needs_enrichment`.
- `memory_enrich(memory_id, content, expected_author_hash)` appends an encrypted
  machine-owned update using the existing \`revise\` event format if and only if the author content still has the
  expected hash and differs from the last enriched baseline. Replays are safe.
  It does **not** edit the author body or automatically invoke another LLM.
- `memory_graph_projection(limit=200)` returns up to 1,000 non-archived graph
  nodes, their internal edges, a journal checkpoint and deterministic
  `projection_hash`. This is in-memory only; no plaintext cache is written.

Existing operations extended compatibly:
- `memory_add`: `epistemic_status`, `intent`, `evidence_ref`.
- `memory_link`: `epistemic_status`, `intent`, `evidence_ref`, `origin`.

The status is **self-reported metadata**, not a verification. Old records have
an implicit `unreviewed` epistemic status. `evidence_ref` points to possible
evidence; EvidenceGate still decides whether it is valid. Link qualifiers are
stored in the encrypted event and survive journal replay and `unlink`.

## Author/machine ownership and hashes

The native memory body is author-owned. Machine enrichment is a separate field
in the encrypted journal. The enrichment basis is a hash of the **body only**.
This keeps machine edits from re-triggering themselves. After `memory_revise`,
`memory_read` marks prior enrichment `enrichment_stale=true`; the next gate
will require a new author hash. A mismatch at append time fails closed.

The separate, optional Markdown helper in `knowledge_evolution.py` implements
the portable-note variant:

```text
# Human-owned content
## End Index Hash
## AI Enrichment
Machine-owned additions
```

`author_hash` covers only content above the sentinel;
`machine_hash` covers content below it;
`file_hash` covers the entire file.
A machine edit changes `file_hash` (reindex) but not `author_hash`
(no retrigger). A persistent `last_enriched_author_hash` baseline is required
to decide whether to enrich. Mutations above the boundary are rejected on
optimistic concurrency mismatch.

## Typed relations and provenance

`RELATIONS` provides a compact *advisory* vocabulary:
`derived_from`, `implements`, `tests`, `supports`, `contradicts`,
`proposes`, `authorizes`, `executes`, `supersedes`, `depends_on`, etc.
Existing custom links remain valid. In particular:

- `PROPOSES` does not mean `EXECUTES`.
- `TESTS` does not itself prove the test passed.
- `supports` is not an EvidenceGate admission.
- `derived_from` continues to power cascading staleness.

Projections preserve relation direction, provenance qualifiers, origin, evidence
references and status. Their `evidence_verified` flags are always `false`;
the projection cannot confer authority to its own assertions.

## Optional graph sidecar

A future LadybugDB adapter can consume `memory_graph_projection`, track
`journal_seq` + `journal_digest`, and rebuild derived indices if it falls
behind or fails. **No live dual write or LadybugDB process is deployed here.**

Important: merely writing to two stores concurrently is not atomic. A
production sidecar must reconcile from the encrypted journal (transactional
outbox/replay), validate checkpoints and limit its access. Writing a plaintext
projection to disk weakens the current encrypted-vault threat model and
requires an explicit owner decision and access controls.

## Test receipt

```sh
cd /home/mirbi/projects/noosphere-knowledge-evolution-r01
PYTHONPATH="$PWD:$PWD/noosphere_lite" python3 -m unittest discover -s tests -p 'test_*.py'
```

Verified locally on feature branch: 145 tests passed, including journal replay,
two-hash retrigger prevention, optimistic concurrency, revision staleness,
encryption, provenance qualifiers and bounded graph projection.

## Non-goals and remaining work

- No migration of the private Noosphere graph.
- No automatic schema approval, confidence inflation or deletion of history.
- No unattended transfer of private data to a public repository.
- No claim that a working LadybugDB index has been deployed.
- Tests are a feature-branch verification, not production acceptance.
