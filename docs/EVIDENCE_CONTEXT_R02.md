# Evidence Context R02 — explicit retrieval trust boundary (2026-11-08)

R02 makes the difference between *searching notes* and *retrieving observations bound to sources* machine-readable. It does **not** certify the truth of the source. No proprietary server code, forum features, professional extensions, private facts, tokens or customer data are included.

## New MCP retrieval behavior

- `memory_search(query)`: existing search, now with `evidence_status=unreviewed_legacy_memory` and `truth_guaranteed=false` on every hit. Evidence claims and tombstones remain excluded.
- `memory_context(query, ..., source_grounded_only=false)`: backwards-compatible legacy memories, now **explicitly marked unreviewed**. Setting `source_grounded_only=true` switches to source-grounded context and excludes all legacy notes.
- `memory_source_grounded_context(query, scope="default", as_of=null, max_chars=10000)`: dedicated strict context with a bounded set of complete evidence capsules, source digests, conflicts and rejection counts.
- `memory_evidence_context(...)`: lower-level R01 evidence lookup remains available.

The strict read path uses `EvidenceGate.query`, so it inherits retraction tombstones, stale-source and dependency checks, conflict vetoes and explicit validity bounds. The bounded adapter **drops entire oversized capsules** instead of truncating evidence hashes or values, and reports `insufficient_context_budget`.

Do not treat `source_matched_only` as independently reviewed or guaranteed world truth. `independently_verified=false` and `truth_guaranteed=false` are explicit. For historical queries supply a timezone-aware `as_of` timestamp; time-filtered legacy notes cannot enter strict historical context.

### Example (conceptual MCP tool call)

```
memory_source_grounded_context(query="portfolio", scope="default", max_chars=4000)
```

Strict mode does not silently backfill with unrestricted memories when no evidence is found. It returns `insufficient_evidence`, a conflict, or a budget status instead.

### Trust and authorization

`scope` is only a retrieval partition and is **not** an ACL. The Lite MCP server uses local stdio. Do not expose it to untrusted users without an authenticated authorization layer. The system does not automatically infer facts from plain notes, approve an author's own assertions, or expose private Noosphere server evidence.

### Tests

`PYTHONPATH=. python3 -m unittest discover -s tests -q`

The R02 tests cover unreviewed labelling, evidence-only retrieval, immutable rejection, conflicts, atomic evidence budgeting, strict historical access and input validation. Revisit these tests whenever query ranking or memory compaction changes.
