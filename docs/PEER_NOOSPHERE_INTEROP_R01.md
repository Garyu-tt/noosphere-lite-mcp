# Peer Noosphere interoperability R01

Recorded 2026-11-09 UTC. Independent read-only Python adapters for two public
projects sharing the name Noosphere. This is a portable core feature: publish
the same Python code and tests to the public GitHub project and the owner's
local installation. Only private on-host agent GET/forum/invoke wiring is local.

## Upstream compatibility

* https://github.com/JinNing6/Noosphere is an Apache-2.0 reviewed coding
  Skill registry. Ingest only its canonical shared_skills/registry.json and
  only uniquely active immutable release metadata. SHA-256 and exact byte size
  are mandatory before returning any SKILL.md content. Withdrawal and
  replacement are fail-closed. Maintainer review is not independent proof
  of applicability.
* https://github.com/SweetSophia/noosphere is an Apache-2.0 self-hosted
  Markdown wiki and agent memory. Its documented authenticated GET /api/export
  returns an article ZIP with YAML frontmatter. The owner supplies the ZIP
  and the actual instance HTTPS origin explicitly. We parse a conservative
  subset of simple frontmatter metadata. No upstream private instance is
  accessed, and no credentials are requested. Restricted-tagged articles
  are skipped by default. Article contents stay out of the peer metadata DB.

Both repositories are independent: no official partnership, direct
service-to-service federation, shared trust or joint operation is implied.

## Owner commands

Run in an isolated project Python environment:

    python -m noosphere_lite.peer_cli sync-skills --db /path/to/peers.sqlite3
    python -m noosphere_lite.peer_cli skills --db /path/to/peers.sqlite3 --query sqlite
    python -m noosphere_lite.peer_cli skill --db /path/to/peers.sqlite3 --name skill-name

For a private wiki, obtain an authorized ZIP separately via its documented
READ-scoped /api/export endpoint, then:

    python -m noosphere_lite.peer_cli import-wiki --db /path/to/peers.sqlite3 --zip /path/to/authorized-export.zip --origin https://your-wiki.example

Never publish the owner's SQLite DB or ZIP to GitHub. The raw registry URL
is pinned to public GitHub HTTPS, no redirects, bounded response bodies.
No Skill or wiki content is executed. Retrieved Skills are untrusted guidance
requiring applicability checks and real project tests.

## Attach to existing metagraph

The peer DB provides the same sources, items and versions tables as the
existing evidence importer. Attach read-only as the schema alias peers;
then call noosphere_lite.federation.import_live(db, source_schema="peers").
Build the graph in disposable storage first, check foreign endpoints and
SQLite integrity, then atomically publish.

Upstream published_at / updatedAt are third-party claims, distinct from
the local recorded observed_at timestamp.

## Limitations

* No scheduled crawler or automated writeback to peers.
* No auto-installation, Skill execution, publication, version approval,
  private API tokens, or agent forum sync.
* Historical digests are retained as observed versions; registry validation
  proves byte identity relative to one observed snapshot, not truth.
* The ZIP parser supports simple top-level scalar fields and YAML lists.
  It deliberately does not interpret arbitrary YAML tags or nested structures.
