# Memory Synthesis R01 — optional research example

Published 2026-11-08. This original, independent implementation is distributed under the repository's GPL-3.0-or-later terms. It is NOT the encrypted Noosphere Lite vault, its MCP API, or the professional edition.

**Security boundary:** This sidecar stores plaintext records and source paths in SQLite/FTS5. Do NOT use it with secrets, private chats, personal records or production databases. No automatic live Noosphere integration, no network access, no forum, no admin panel, no NLV1 replication.

## Implemented independently

- Exact-source quotation versus explicitly inferred assertions.
- SHA-256 source check, optional pinned Git commit verification and source drift status.
- Distinct recorded, observed and valid-time metadata; historical queries require known valid time.
- Explicit supersession within one project, actor and slot; no word-overlap retirement.
- Negative knowledge and invariants cannot be casually overwritten.
- Superseded factual history remains queryable.
- Independent-session source references cannot automatically promote inference to truth.
- SQLite FTS5/BM25 search; optional feedback reranking is off by default.
- Short session briefing with negative rules, invariants, open loops and freshness flags.
- Event-chain checksum and minimal forgetting tombstones (not cryptographic erasure).

## Usage

Requires Python 3.11+, SQLite FTS5 and (only for Git evidence) git; no third-party Python packages.

Run from the repository root:

    python3 -m unittest discover -s examples/memory_synthesis -v
    python3 examples/memory_synthesis/memory_synthesis.py --db /tmp/noosphere-synthesis-demo.sqlite3 add --project demo --actor alice --slot residence --kind fact --text "Alice lived in Lisbon" --source-path /path/to/public-evidence.txt --valid-from 2026-01-01T00:00:00Z
    python3 examples/memory_synthesis/memory_synthesis.py --db /tmp/noosphere-synthesis-demo.sqlite3 recall Lisbon --project demo --at 2026-02-01T00:00:00Z
    python3 examples/memory_synthesis/memory_synthesis.py --db /tmp/noosphere-synthesis-demo.sqlite3 brief demo
    python3 examples/memory_synthesis/memory_synthesis.py --db /tmp/noosphere-synthesis-demo.sqlite3 audit

The evidence file must exist. Offset-aware dates normalize to UTC; unknown valid-time is kept unknown, not guessed. Use --require-current-source on recall when drifted or missing evidence must be excluded.

## Threat model and limitations

1. Plaintext storage is unsuitable for private data; permissions on the SQLite file are not encryption.
2. No tenant authorization, signed audit log, independent identity validation or distributed writer protocol.
3. Digest chaining detects unsophisticated modification, not forgery by a database administrator.
4. Forget deletes content from active records and FTS5, but does not securely erase SQLite free pages/WAL, filesystem snapshots, original files, backups or remote copies.
5. A matching source hash does NOT prove factual accuracy. Corroboration and feedback cannot change the trust class.
6. Search is lexical, not semantic; no claimed improvement over BM25 baseline; no production deployment.
7. For professional or encrypted-vault integration, review security and permissions separately.

## Research sources, licenses and attribution

See the version-pinned research registry in docs/research-memory-candidates-2026-11-08.md and its JSON companion. No donor project code was copied into this example.

- Agents Remember by Readone Mohamed: MIT, revision 81180617aed517835314526b8309d37d5be8b3b7.
- Daimon: Apache-2.0, revision d3d58c26a25229679fe60d47e34e5284e3602120.
- Primnox Memory-system: Business Source License 1.1 with a non-commercial use grant; commercial use requires separate permission until the license change. No Primnox implementation copied.
- Engram: public conceptual descriptions only, with no source code/text/chart reuse.

Future direct imports must follow each origin's license and retain required notices. The closed/professional Noosphere edition and forum are NOT part of this open example.
