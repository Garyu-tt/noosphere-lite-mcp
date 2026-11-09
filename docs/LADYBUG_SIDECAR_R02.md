# LadybugDB ephemeral graph sidecar R02

**Status:** tested opt-in development integration, **not deployed** into the running
production Noosphere service. Keeps the encrypted NLV1 dual-mirror journal as
the source of truth.

## Design and privacy

- The Ladybug Python library opens **only** `ladybug.Database(":memory:")`.
  There is no public API in this adapter for a filesystem database path.
- Metadata from `memory_graph_projection()` (including titles, source labels,
  intent and evidence references) are copied to process memory; **memory
  bodies and machine-enrichment text are never imported**.
- Even titles and relation metadata may be sensitive. Do not expose the MCP
  endpoint to unauthorized clients. No public graph UI endpoint is started.
- The only durable data remains Noosphere's existing encrypted journals.
- This is **not** a distributed transaction or parallel dual-write. Queries
  explicitly synchronize from the journal. If the sidecar fails, the journal
  is unaffected; sidecar state is disposable and can be rebuilt.
- The adapter does not declare facts verified. Epistemic statuses and source
  pointers are still unreviewed until accepted by the independent EvidenceGate.

## Install and enable (isolated testing first)

```sh
cd /path/to/noosphere-lite-mcp
python -m venv .venv
.venv/bin/python -m pip install -e '.[ladybug]'
# Configure NSL_PRIMARY, NSL_MIRROR, NSL_KEY_FILE as for normal MCP.
export NSL_LADYBUG_EPHEMERAL=1
.venv/bin/python -m noosphere_lite mcp
```

The flag registers only three additional MCP tools:

- `memory_ladybug_sync()`: full bounded refresh; returns journal sequence,
  digest, projection digest and whether it refreshed.
- `memory_ladybug_status()`: last completed graph checkpoint (not a live
  assertion that no concurrent writer exists).
- `memory_ladybug_neighbors(memory_id, direction="both")`: synchronize first,
  then traverse at most 200 one-hop typed directed relationships; accepted
  directions `both`, `in`, `out`. User input is bound as a query parameter.

No `NSL_LADYBUG_EPHEMERAL` flag means **no additional tools, dependency
imports, database creation, or graph synchronization**.

## Consistency model

1. `MemoryVault.graph_projection(limit=1000)` takes a consistent encrypted
   journal snapshot under the vault lock and generates a deterministic graph
   hash. An incomplete snapshot (`truncated=true`) is **rejected**.
2. In one Ladybug write transaction, the adapter deletes the old derived
   graph, inserts its current nodes and typed edges, then writes a receipt
   with source journal sequence/digest, projection hash and row counts.
3. A failed materialization rolls back and leaves the previous checkpoint.
4. Repeating an unchanged journal sync is a no-op **if the materialized row
   counts still match**. A mismatch forces a rebuild.
5. An eventual later sync catches up with concurrent writes after its
   snapshot. A read concurrent with a write is not claimed linearizable.

**Scaling note:** this R02 prototype supports at most 1,000 active memories
per ephemeral projection. It deliberately refuses partial graph imports; it
uses per-node parameterized Cypher updates rather than optimized bulk COPY.
Production-size graphs require paginated, checkpointed ingestion and measured
query/refresh load before expanding that limit. Stored status is not itself
a substitute for an EvidenceGate check.

## Tests

```sh
PYTHONPATH="$PWD:$PWD/noosphere_lite" python3 -m unittest discover -s tests -p 'test_*.py'
```

Integration tests use the **real** LadybugDB 0.20.4 library when available and
skip when the optional package is absent. Cases include first sync, idempotence,
directed edge queries, parameter binding, journal revision and stale propagation,
unlink/archive, simulated failure mid-transaction + rollback + retry, graph
tampering count-rebuild, truncation veto, and MCP tool registration.

Relevant upstream documentation:
- https://docs.ladybugdb.com/client-apis/python/
- https://docs.ladybugdb.com/cypher/transaction/
- https://docs.ladybugdb.com/get-started/prepared-statements/
