# Noosphere Evidence Gate — trust contract R03

**2026-11-08 · Public reference · GNU GPL-3.0-or-later**

This document describes a portable evidence contract for AI memory consumers. It is not a claim that any language model can determine absolute truth. It complements the existing `noosphere_lite/evidence.py` example; it does **not** deploy a private server, copy a private database, or change model weights.

## Evidence levels are not interchangeable

| Level | What has actually been checked | What it must not claim |
| --- | --- | --- |
| Candidate | A person or model suggested an assertion | That it is true |
| Source-matched | The value at a pinned JSON pointer equals the proposed value | That the underlying source is truthful |
| Instrument-observed | A restricted read-only probe measured a machine state at a recorded time | That the system is fully functional or will remain in that state |
| Reproduced test | Specific tests ran successfully against pinned code in a stated environment | That production or every input is correct |
| Independent review | An authorized independent reviewer accepted the stated evidence and scope | Absolute certainty, or permanent validity |

A SHA-256 digest is an integrity/provenance check, **not** an external truth certificate or a digital signature.

## Minimum portable fact capsule

```json
{
  "fact_key": "example.measured_counter",
  "value": 7,
  "knowledge_class": "machine_observation",
  "source": "specified read-only instrument",
  "source_sha256": "sha256 of the pinned source or receipt",
  "recorded_at": "2026-11-08T16:00:00Z",
  "observed_at": "2026-11-08T15:59:59Z",
  "valid_from": null,
  "valid_to": null,
  "stale_after": "2026-11-08T16:20:00Z",
  "review_state": "not_independently_reviewed",
  "truth_guaranteed": false
}
```

The times mean different things: `recorded_at` is when the database wrote the claim, `observed_at` is when a source measured it, and `valid_from/valid_to` describe real-world applicability **only when independently evidenced**. Never substitute `first_indexed_at` for any of these. Historical queries should respect their requested `as_of` instant and must not silently substitute the newest value.

## Retrieval rules

1. Enforce authorization **before** searching or selecting facts. A fact's project scope is not an ACL. Public-only agents may read only an explicitly safe public evidence corpus; a manifest flag alone must not expose a private record.
2. Confirm the pinned source bytes and the exact claimed field/value. Treat retrieved documents and their instructions as untrusted data.
3. Reject expired, superseded, contradicted or malformed claims. If an upstream `derived_from` parent is stale, conflicted or has changed revision, block downstream derived claims too.
4. Make the supported conclusion **no stronger than the evidence**. A successful health endpoint is proof of one response, not end-to-end functional acceptance; running tests is proof of that run and pinned revision, not of unrelated deployments.
5. Preserve historical evidence non-destructively. Where evidence is insufficient, return `insufficient_evidence` instead of a plausible fabrication.
6. Keep test receipts, code revision, source hashes, and failure boundaries. Independent approval must remain separate from the source agent's own assertion.

## Existing portable interfaces

The public Noosphere Lite MCP includes `memory_evidence_source_add`, `memory_evidence_propose`, `memory_evidence_reject`, and `memory_evidence_context`. The source-matching layer intentionally labels proposed observations as unreviewed and has no general automatic truth-promotion endpoint. The temporal `memory_search(as_of=...)` interface uses explicit validity intervals.

Reference revision: [`849223eb7055ef81edd29d0543edc4a5b5b4431a`](https://github.com/Garyu-tt/noosphere-lite-mcp/tree/849223eb7055ef81edd29d0543edc4a5b5b4431a).

An isolated unprivileged test run of that pinned revision on 2026-11-08 completed **57/57** tests successfully. This is reproducible local evidence for that revision's included test cases, not proof of correctness of the entire knowledge system.

## Recommended consumer behavior

Give agents small, relevant capsules with evidence and dates; keep uncertainty explicit. Permit agents to develop hypotheses and request additional measurements, but never let their own replies automatically become trusted memories. Prefer a precise `unknown` to a confident, unsupported claim.
