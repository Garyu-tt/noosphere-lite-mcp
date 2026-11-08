# Noosphere CodeContext R05 — evidence-first programming

Recorded: 2026-11-09 (UTC). This is a **shared-core** component: public
GitHub and the owner-operated Noosphere run byte-identical
`noosphere_lite/code_context_r05.py`.

## What it does

Given a programming goal and optional target-project constraints, R05
produces a **bounded evidence context packet** from existing read-only
CodeFabric and Live Knowledge Links databases:

- Candidate Python functions with qualified names, relative paths,
  exact indexed file SHA256, observed timestamps, optional current-file
  freshness checks, static call counts and explainable retrieval scores.
- Public source *metadata* with source URL, observation timestamp,
  upstream-provided update timestamp, license hint and content digest.
- Curated recipe choices, annotated as eligible, conditional or
  ineligible based on language, CPU/GPU target, sorted-input, negative
  weights, and whether third-party dependencies have been approved.
- An explicit test/review/benchmark plan. **No automatic code execution,
  installation, patching, merging, publishing or production changes.**

The retrieval algorithm is stateless, side-effect-free, source bounded,
and returns clear uncertainty/status labels. Source claims remain
unverified. Function-call discovery cannot prove runtime dispatch.
Current results are lexical candidates rather than embedding-based
semantic equivalence. Similar AST bodies are not automatically safe
substitutes.

## Portable Python API

```python
from pathlib import Path
from noosphere_lite.code_context_r05 import plan

packet = plan(
    "sqlite transaction batching",
    overlay=Path("overlay.sqlite3"),
    code=Path("codefabric.sqlite3"),
    semantic=Path("semantic.sqlite3"),
    live=Path("knowledge_links.sqlite3"),
    project="example-project",
    language="python",
    hardware="cpu",
    allow_external=False,
    limit=8,
)
assert packet["truth_guaranteed"] is False
```

The library does not assume user filesystem locations or contact external
services. Optional `source_root` must be an owner-controlled directory;
the freshness check refuses symlinks, traversal and oversized files.

## Optional private deployment adapter

The owner-operated AgentForge can expose the library through its
existing authenticated loopback API. This deployment-only route is
**not part of the public package**:

```http
GET /v1/knowledge/code-context?q=sqlite%20concurrency&project=neural-cms-r01&language=python&limit=8
Authorization: Bearer <owner-approved-agent-token>
```

Supported query keys: `q`, `project`, `language`, `hardware`,
`capability`, `limit`, `sorted_input`, `negative_edges`,
`allow_external`. Boolean choices use `true`, `false` or `unknown`.
Unknown/guest/quarantined external workers cannot inspect the private
context. This route never delegates content to Gemini.

Private agent dispatch, inter-agent GET and the private forum remain
local extensions. Shared core logic, provenance, indexing and tests
must remain available on *both* branches.

## Automated regression tests

```shell
python3 -m unittest discover -s tests -p 'test_code_context_r05.py' -v
python3 -m unittest discover -s tests -p 'test_federation*.py' -v
```

Synthetic tests cover constraints, live/public source metadata,
local-file fingerprint freshness, path safety, version provenance,
Russian capability aliases and nonexecution of malicious-looking text.

### Current limitations

No verified best-performing implementation selection, cross-language
compiler AST analysis, code rewriting or independently validated
GitHub/Stack Overflow solution quality. Availability of old sources
can drift between source observations; the packet exposes its
timestamp rather than pretending to know current truth.

For the production engineering loop: manually inspect exact current
source -> characterize baseline behavior -> review dependency licenses
-> generate candidate in a disposable worktree -> run independent
correctness and representative benchmark tests -> review patch before
a deliberate merge.
