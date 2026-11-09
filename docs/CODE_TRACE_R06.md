# Noosphere CodeTrace R06 — static calls and reuse evidence

Recorded 2026-11-09 UTC. The shared module `noosphere_lite/code_trace_r06.py`
is portable (Python standard library, SQLite read-only) and belongs in both
the public repository and the owner's local Noosphere.

## What it implements

A bounded explanation of an indexed Python function's source provenance,
likely call dependencies, unresolved/dynamic calls, possible incoming
callers and same-body AST matches from other projects.

```python
from pathlib import Path
from noosphere_lite.code_trace_r06 import inspect_code

result = inspect_code(
    Path("semantic_r03.sqlite3"),
    "fed:semantic:fn:YOUR_INDEXED_FUNCTION_ID",
    depth=2,
    limit=30,
    include_incoming=True,
)
```

Response includes `root`, `functions`, `calls`,
`unresolved_calls`, `ast_duplicate_candidates`, `truncated`,
`truth_guaranteed=false` and `review_gates`. Each node retains
project-relative path, source SHA256, AST-observation timestamp and function
signature. No original source contents are executed or copied.

**Critical qualification:** matching AST bodies is only a lexical/static
candidate. It cannot prove that imports, globals, state, closures, side effects,
calling contracts, or licensing are compatible. A call target derived from AST
name resolution is not proven runtime dispatch. This component cannot
autonomously integrate code into a project.

### Performance bounds

The API permits depths 0..3 and up to 60 visible function nodes; each
expanded function inspects at most 120 static calls. Incoming callers are
read for the selected root only. Duplicate groups are sampled up to four
fingerprints and twenty peers per fingerprint. Every result indicates when
data was truncated. It performs no network requests or source imports.

### Local-only integration

The owner's authenticated AgentForge adapter adds:

```text
GET /v1/knowledge/code-trace?ref=fed:semantic:fn:...&depth=2&limit=30&incoming=true
```

Local agent/owner authentication is required. Quarantined Gemini and guest
accounts are refused. This adapter and its private filesystem locations do
not belong to the public source tree. The public module remains reusable
independently of the owner's private service.

### Validation

```sh
python3 -m unittest discover -s tests -p 'test_code_trace_r06.py' -v
```

Synthetic tests cover incoming/outgoing calls, unresolved targets,
cross-project AST matches, hard limits, invalid IDs and read-only access.

Next target: characterized source-level test synthesis in isolated
worktrees with independent gates and measured benchmark evidence.
