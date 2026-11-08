# Researching agent memory for Noosphere Lite (2026-11-08)

**Status:** Public research catalog, NOT a claim that all mechanisms ship in Lite 0.3.0. Original independent notes; no donor source code is included.

Русское резюме: 27 полезных идей из четырёх источников, разделённых по происхождению, зрелости и лицензии. Реализованные элементы находятся в examples/memory_synthesis. Остальное — кандидаты для тестирования, а не подтверждённые функции.

The data version is also available in [JSON](research-memory-candidates-2026-11-08.json); unknown historical dates are kept null, not guessed. Date of review is NOT the creation date of any donor concept.

### Agents Remember

Source: https://github.com/Foxfire1st/agents-remember/tree/ar/260928_maintained-invariant-knowledge

Revision: 81180617aed517835314526b8309d37d5be8b3b7. License: MIT.

- **file-addressed-memory** [invariant]: Use deterministic file-path cards for code-specific context, not a search guess.
- **code-memory-provenance** [invariant]: Bind knowledge cards to source commit and content digest; report drift and absent inputs.
- **atomic-code-memory-review** [idea]: Validate candidate source tree and matching knowledge tree before publishing either.
- **append-only-curator-history** [idea]: Preserve curator judgments, reviewed no-impact decisions and rejected claims.
- **derived-index-not-truth** [idea]: Keep authored versioned knowledge separate from rebuildable query indexes.

### Daimon

Source: https://github.com/Daily-Nerd/daimon

Revision: d3d58c26a25229679fe60d47e34e5284e3602120. License: Apache-2.0.

- **verbatim-vs-inferred** [invariant]: Allow verbatim only for checked exact source text; label model interpretations as inferred.
- **corroboration-is-not-truth** [invariant]: Session corroboration records repetition but never makes a claim independently verified.
- **session-handoff-brief** [idea]: Emit scoped session-start briefs with unresolved decisions and stale knowledge first.
- **negative-knowledge-ledger** [idea]: Preserve failed attempts and scoped constraints instead of repeatedly retrying them.
- **privacy-tombstone** [idea]: Keep minimal deletion tombstones without retaining deleted content in normal indexes.
- **code-symbol-drift** [idea]: Anchor project assumptions to source locations and detect changes.

### Primnox Memory-system

Source: https://github.com/Primnox/Memory-system

Revision: cc9e480427e9191ba6570e1c464eea50469531f4. License: BSL-1.1 (non-commercial additional grant; commercial license required until change date).

- **time-validity-history** [idea]: Separate valid time from observation and recording time for historical queries.
- **actor-slot-supersession-guard** [invariant]: Never retire a fact solely on lexical similarity; require same entity and predicate slot.
- **entity-folder-slot** [idea]: Organize facts under entities and stable attribute slots; preserve source identity.
- **extraction-before-search** [idea]: Benchmark fact extraction separately from ranking because extraction may dominate quality.
- **primnox-license-boundary** [limit]: Do not vendor BSL source into potentially commercial/open systems without permission.

### Engram

Source: https://drksci.com/research-engram#2-ten-mechanisms

Revision: Web research snapshot reviewed 2026-11-08. License: Source-code reuse not established; concept descriptions only.

- **tide** [hypothesis]: Experiment with recency reranking against fixed-k baselines.
- **pheromone** [hypothesis]: Experiment with positive evidence feedback on traversed paths only after held-out tests.
- **ring** [hypothesis]: Experiment with iterative rescoring; verify that it really changes the ranking.
- **web** [hypothesis]: Experiment with one-hop entity graph traversal on multi-hop questions.
- **bloodhound** [hypothesis]: Experiment with learned path navigation trained on disjoint non-evaluation cases.
- **horizon** [hypothesis]: Experiment with hyperbolic latent geometry for general versus niche topics.
- **loom** [hypothesis]: Experiment with neighbor agreement without mistaking repeated claims for independent proofs.
- **coral** [hypothesis]: Experiment with adaptive growth, consolidation, heirs and error checks by ablation.
- **canopy** [hypothesis]: Experiment with curated bounded-branching topic trees for candidate search.
- **glyph** [hypothesis]: Experiment with self-describing compressed memory and cross-model cold-read fidelity.
- **benchmark-integrity** [negative]: Never cite withdrawn historical Engram scores as validated; require equal k, disjoint seeds and official metrics.

## What actually ships in the optional example

The independently written optional Python sidecar implements provenance checks, temporal validity, scoped supersession, immutable negative safeguards, explicit inferential trust, SQLite FTS5 search and manual feedback. It is **plaintext**, not the encrypted NLV1 core. See [the example README](../examples/memory_synthesis/README.md) for threat-model limitations and test commands.

## Evidence and publication gate

1. Pin source revisions, content digests and semantic claims separately. A Git file still existing does not make its statements true.
2. Separate assertion/event time, observation time, recording time and truth-validity interval. Never invent a historical date.
3. An LLM extraction, independent test or user review may change trust classification only by an explicit evidence-based decision. Repetition alone is not proof.
4. Compare all retrieval proposals against BM25 and dense baselines at the same k with held-out query splits, stable seeds, official retrieval metrics, confidence intervals and saved logs.
5. Keep failures, negative results, withdrawn claims and permissions visible. Do not merge new ranking methods into the encrypted core until their effect and privacy impact have been tested.
6. Preserve the user-facing public/professional separation: neither forums, control-plane credentials, internal agents nor owner-only memory belong in this release.

## Licensing and boundaries

Agents Remember MIT and Daimon Apache-2.0 permits code reuse with notices; we have not copied their code. Primnox is BSL 1.1 with a non-commercial research grant and commercial license restriction; source copying is intentionally excluded. Engram is described from public research prose only. The original Noosphere example code is part of this repository under GPL-3.0-or-later.
