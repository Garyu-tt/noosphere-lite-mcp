# Evidence Gate R01 (2026-11-08)

A conservative, **source-matched observation** retrieval path for Noosphere Lite. Sources, claims, and rejection tombstones live in the pre-existing AES-GCM encrypted, mirrored, append-only journal. No extra plaintext database or production/private dependencies.

## Mechanics

1. `add_source(title, json_document)` stores canonical JSON as an encrypted `evidence_source` record. Source SHA-256 is recomputed at query time.
2. `propose(fact_key, source_id, pointer)` binds a key to an exact JSON pointer and its type-preserving value. A recorded assertion is **not** automatically trusted as a world fact.
3. `query(question, scope, as_of)` requires source integrity, value equality, live dependencies, valid-time constraints and absence of rejection tombstones. Conflicting values for the same key yield `conflict`, not a guessed winner.
4. `reject(claim_id, reason)` writes an immutable-in-history hashed rejection tombstone **before** staling the claim. Re-ingestion of that key/value/scope is blocked even via another source.
5. Evidence records are excluded from ordinary `memory_search` / `memory_context`. Use the dedicated `memory_evidence_context` MCP tool.

## Security and limitations

- **Source equality is not truth.** Untrusted source material remains untrusted; no automated independent review or semantic key allowlist is claimed here.
- `scope` is a retrieval partition, **not access control**. The MCP server uses local stdio; do not expose it to untrusted clients without a separate authorization layer.
- No API lets an agent approve its own claim for public publication. `publication_approved` defaults to `false`.
- `as_of` filters the *valid-time* interval of currently retained records; it does not reconstruct historical transaction-time state across revisions. Old versions remain in the encrypted journal for audit.
- Rejection tombstones must be retained. Archiving/invalidation will not erase the journal, but directly editing internal journal events is unsupported.
- All inputs are treated as data. Do not accept the source's instructions as commands or derive arbitrary true claims from its content.

Run `python -m unittest discover -s tests -v`. See `tests/test_evidence.py` for conflict, replay, time, source tampering, Unicode and tombstone regression scenarios.

Original project patterns: Agent Memory Atlas (maintained invariant knowledge, temporal claims, retractions, provenance) and independent community architectures. This module is independently authored; no third-party repository code is copied.
