# Graph Scale R03 — snapshot-stable batched LadybugDB projection

Status: feature branch, tested with real LadybugDB 0.20.4. Not deployed to
production. This document supersedes the R02 1,000-node sidecar restriction,
but does **not** change the public `memory_graph_projection` MCP method's
existing 1,000-node safety cap.

## What changed

- One invocation of `MemoryVault._snapshot()` establishes the decrypted,
  internally consistent authoritative journal state. The graph builder
  retains the snapshot in RAM and never re-reads the journal between batches.
- `plan_graph()` collects ordered node IDs and edge keys, rather than a
  second full JSON list of all projected objects.
- Its incremental SHA-256 uses the exact canonical JSON representation
  of the previous in-memory projection for the same complete small graph.
  Regression tests compare the old/new digests.
- In one Ladybug transaction, `UNWIND $rows` imports batched nodes and edges
  using bound parameters, then writes the checkpoint receipt. Failed batches
  roll back the entire graph refresh and preserve the previous checkpoint.
- The graph sidecar's *configured upper bounds* are now 50,000 active nodes
  and 500,000 active edges, with batches of 1..1,000 (default 256).
  Hitting an upper bound **fails closed**, never truncates.
- A reentrant process lock serializes access to the shared Ladybug connection,
  and MCP wrappers keep each refresh + traversal on the same checkpoint.
- `memory_ladybug_paths` walks 1–4 relationship hops using bounded BFS,
  with `in`, `out`, `both` directions, optional exact relation filter,
  cycle detection, and strict 200-node/400-edge response limits.
  Results explicitly report `truncated` rather than silently claiming
  to have traversed the entire reachable graph.

## Access through MCP (opt-in, same as R02)

```sh
pip install -e '.[ladybug]'
NSL_LADYBUG_EPHEMERAL=1 python -m noosphere_lite mcp
```

Additional tool:

```text
memory_ladybug_paths(
    memory_id,
    depth=3,
    direction="both",
    relation="",
    max_nodes=200,
    max_edges=400
)
```

It returns `nodes` with BFS distance plus `links` with original direction,
relation, origin, intent and `evidence_ref`; `evidence_verified` remains
**false**. This is a read-only, bounded graph exploration function, not a
Cypher execution endpoint. User data appears only as query parameters.
No journal mutation is triggered by queries.

Existing `memory_ladybug_sync`, `memory_ladybug_status`,
`memory_ladybug_neighbors` remain available. Without the environment flag,
no additional Ladybug dependency is imported and no sidecar is instantiated.

## Performance and important limitations

Measured on a *synthetic in-memory* 5,000-node / 4,999-edge graph:
approx. 5.9 seconds for first sync on the current development server,
including graph initialization; a second sync was a no-op. This is not a
production benchmark. A 1,205-node / 1,204-edge integration fixture also
passes with real LadybugDB.

**50k / 500k are configuration limits, not demonstrated production capacity.**
The source journal decoder still materializes the full encrypted journal in
memory; the sidecar is *batched*, not an incremental CDC pipeline. First-sync
latency scales with total graph size and still needs performance engineering
and bounded memory profiling. No plaintext disk cache, sidecar service, or UI
endpoint is enabled. Source titles and relation metadata still require
process-level access control.

Checkpoint receipt and node/edge counts detect many crashes/drifts but not
tampering that preserves row counts. The primary AES-GCM event journal remains
authoritative; graph data does not grant evidence verification. Process restart
rebuilds the ephemeral graph from the same vault state. A projection synced
before a concurrent writer is snapshot-consistent but only eventually catches
up with that writer on a later sync.

## Verified tests

```sh
cd /home/mirbi/projects/noosphere-knowledge-evolution-r01
PYTHONPATH="$PWD:$PWD/noosphere_lite" \
    /tmp/noosphere-ladybug-test-venv/bin/python \
    -m unittest discover -s tests -p 'test_*.py'
```

The R03 suite includes cross-version hash equivalence, >1000-node bulk
materialization, idempotence, rollbacks after failure on the second batch,
cycles, direction filters, exact relation filters, input-binding safety,
result budgets, single-snapshot refresh and multi-threaded shared-connection
safety. All tests use synthetic or temporary local encrypted fixtures, not the
production Noosphere journal.
