# Federated Evidence Graph R04 — public / local parity

Recorded: 2026-11-09 UTC. Shared Noosphere core design, compatible with stdlib Python + SQLite.

## Rule: one common core, two deployment fronts

The portable data model, provenance logic, version lineage, search/graph algorithms,
tests and public documentation belong in **both** the public GitHub repository and
the owner-operated local Noosphere. The shared module here is
`noosphere_lite/federation.py`; a byte-identical copy is used by the private
deployment adapter. Changes in the portable code require matching tests and
a matching SHA256 in both deployment fronts.

Only integrations that require private infrastructure stay local:
inter-agent GET/exchange, private agent forum, and invoking on-host agent workers.
Do not ship those adapters, their tokens, private paths, or private user data.

## Purpose

Federate *observations*, not hypothetical truths:

- source record -> observed item -> specific hash-addressed version;
- Python AST function -> source project -> candidate statically resolved calls;
- shared AST fingerprints -> fingerprint hub, not a quadratic full clique;
- optional exact-title keyword match -> programming capability, **always unverified**;
- consistent provenance and bounded source scanning.

The **external source is authoritative only for what was observed**, not the
correctness of the source's claim. Source-provided dates never become
`observed_at` or `valid_from` without evidence.

The shared module has no network access, model interface, filesystem paths,
or code execution. The caller must connect authorized **read-only** databases
through SQLite ATTACH and provide a disposable graph schema.

## Example

```python
import sqlite3
from noosphere_lite.federation import import_live, import_semantic

graph = sqlite3.connect("disposable_index.building")
graph.execute("ATTACH DATABASE ? AS live", ("file:/safe/example-links.db?mode=ro",))
graph.execute("ATTACH DATABASE ? AS semantic", ("file:/safe/ast-symbols.db?mode=ro",))
# Graph tables (nodes, edges) must already exist.
graph.execute("BEGIN")
live_receipt = import_live(graph, source_schema="live")
semantic_receipt = import_semantic(graph, source_schema="semantic")
graph.commit()
```

The final deployer must run SQLite integrity checks, verify all edge endpoints,
validate source lineage, and atomically publish the disposable index. Original
source databases must never be overwritten.

## Test

```sh
python3 -m unittest discover -s tests -p 'test_federation.py' -v
```

The fixture tests check stable ID collision avoidance, historical version
identity, source provenance, epistemic trust labels, bounds, cross-project
fingerprint hubs and idempotence. These are **synthetic engineering tests**, not
benchmarks or proof of the semantic accuracy of upstream material.

## Limitations and future development

- No automated ingestion of all GitHub or Stack Overflow content.
- No automatic code reuse, package install, commit, or production deployment.
- AST matching is not runtime dispatch verification.
- Public web metadata still requires independent fact checks and license review.
- Full multi-language compiler frontends and reproducible performance scoring
  are future work; no “optimal” claim is warranted by keyword matches.

This module is portable open-source functionality. Private agents and
professional operational tooling are not part of the public repository.

## Compact incremental overlay (R04)

The portable `noosphere_lite/federation_overlay.py` can atomically build a small
SQLite sidecar from three read-only input databases: observed live links,
static semantic functions/calls, and programming-capability hubs. A cheap source
fingerprint prevents redundant rebuilds; source changes rebuild only the
sidecar, not an unrelated large knowledge graph. The code does not contain
or require private infrastructure paths, tokens, workers, or network access.

Example in a permitted local environment:

```python
from pathlib import Path
from noosphere_lite.federation_overlay import build, search, neighbors
receipt = build(Path('overlay.sqlite3'), Path('observed-links.sqlite3'),
                Path('semantic-code.sqlite3'), Path('code-catalog.sqlite3'))
results = search(Path('overlay.sqlite3'), 'sqlite', layer='federated')
```

The caller must define proper access controls for its own observations and
perform authoritative fact validation separately. `search` and `neighbors`
return unverified evidence, not machine-validated truth. The overlay is
rebuildable and has no write access to source databases.

```sh
python3 -m unittest discover -s tests -p 'test_federation*.py' -v
```
