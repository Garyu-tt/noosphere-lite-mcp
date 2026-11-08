# Time-aware memory and optional graph interoperability

Status: experimental, additive. Published 2026-11-08 (UTC). This module does **not**
automatically export private data, change encryption, or migrate the primary storage.

## Temporal semantics

- `created` / `updated`: legacy creation and modification audit fields.
- `recorded_at`: UTC time the system persisted a **new** memory or relationship.
- `observed_at`: optional source observation time, requiring an explicit UTC offset.
- `valid_from`, `valid_to`: optional evidence-backed validity period, half-open
  interval `[valid_from, valid_to)`; it describes **when a statement was true**,
  not when it was saved.
- `as_of`: historical filtering on the explicit validity interval only. A record
  with *both* bounds unknown is excluded instead of being falsely treated as
  timeless. Normal search still finds it.
- Historical records with unknown time retain missing values. A later indexing
  date must **never** be silently substituted for the historical event date.
- Relationship creation is dated in new encrypted journal events; old events
  remain readable. The journal still retains all historical event frames.

```python
from noosphere_lite.vault import MemoryVault

# With an already initialized vault named vault:
old = vault.add("Address", "Old residence",
                valid_from="2020-01-01T00:00:00+02:00",
                valid_to="2022-01-01T00:00:00+02:00")
new = vault.add("Address", "New residence",
                valid_from="2022-01-01T00:00:00+02:00")
historical = vault.search("Address", as_of="2021-06-01T00:00:00Z")
```

## Optional graph adapters

`noosphere_lite.interop.networkx_report(nodes, links)`: bounded optional
NetworkX analytics. Explicitly caps total nodes to protect application RAM.
Install NetworkX separately when desired. Analytics is advisory and does not
assert that a lexical correlation is true.

`export_ladybug_csv(nodes, links, destination)`: **plaintext** nodes/edges CSV
staging for evaluation of LadybugDB. It does *not* install, connect to, import
into or benchmark LadybugDB. Benchmark and validate before migration.

`export_okf(nodes, links, destination)`: opt-in Open Knowledge Format v0.2
Markdown/YAML concept bundle. Additional typed-edge information is preserved
in `noosphere-edges.json` (Noosphere-specific extension). It is *not* a claim
of standardized graph-edge round-trip compatibility. Keep native encrypted
data as the authoritative source.

For adapters, only pass a deliberately selected subset of a graph to export.
Never commit generated knowledge export folders to a public repository.

## Verification

- `python -m unittest discover -s tests -v` (14 passed on 2026-11-08).
- No migration of the encrypted journal; original tests for mirror recovery,
  encryption and cascading invalidation still pass.
- Optional integrations remain gated and their speed/usefulness are not
  demonstrated without measurements on representative workloads.
