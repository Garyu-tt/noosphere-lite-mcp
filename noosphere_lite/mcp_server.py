"""MCP stdio adapter; no network listener and no private Noosphere dependencies."""
from .vault import MemoryVault
from .evidence import EvidenceGate
from .briefing import MemoryBriefings
from .context_r02 import context as trust_context
from .git_drift_r03 import GitDriftGuard

def run(vault: MemoryVault):
    try:
        try:
            from mcp.server.mcpserver import MCPServer as MCPApp  # MCP SDK 2.x
        except ImportError:
            from mcp.server.fastmcp import FastMCP as MCPApp  # MCP SDK 1.x
    except ImportError as e:
        raise RuntimeError("Install dependencies: pip install -e .") from e
    app = MCPApp("noosphere-lite-mcp")
    git_guard = GitDriftGuard.configured(vault)
    evidence = EvidenceGate(vault, git_guard=git_guard)
    briefings = MemoryBriefings(vault, git_guard=git_guard)

    @app.tool()
    def memory_add(title: str, body: str, tags: list[str] | None = None,
                   kind: str = "note", source: str = "",
                   valid_from: str | None = None,
                   valid_to: str | None = None,
                   observed_at: str | None = None,
                   epistemic_status: str = "unreviewed",
                   intent: str = "", evidence_ref: str = "") -> dict:
        """Persist a claim with its explicitly unverified epistemic metadata."""
        return vault.add(title, body, tags, kind, source,
                         valid_from=valid_from, valid_to=valid_to, observed_at=observed_at,
                         epistemic_status=epistemic_status, intent=intent,
                         evidence_ref=evidence_ref)

    @app.tool()
    def memory_search(query: str, limit: int = 10,
                      as_of: str | None = None) -> list[dict]:
        """Find memories, optionally filtering by explicitly known validity at an instant."""
        hits = vault.search(query, limit, as_of=as_of)
        for hit in hits:
            hit["evidence_status"] = "unreviewed_legacy_memory"
            hit["truth_guaranteed"] = False
            hit["git_provenance"] = git_guard.status(hit["id"])["status"]
        return hits

    @app.tool()
    def memory_suggest_links(memory_id: str, limit: int = 10) -> list[dict]:
        """Suggest candidate cross-domain links without creating or verifying them."""
        return vault.suggest_links(memory_id, limit)

    @app.tool()
    def memory_read(memory_id: str) -> dict:
        """Retrieve one specific memory's complete content."""
        return vault.read(memory_id)

    @app.tool()
    def memory_link(source_id: str, target_id: str, relation: str = "related",
                    epistemic_status: str = "unreviewed",
                    evidence_ref: str = "", intent: str = "",
                    origin: str = "") -> dict:
        """Add a directed relation with explicitly unverified provenance metadata."""
        return vault.link(source_id, target_id, relation,
                          epistemic_status=epistemic_status,
                          evidence_ref=evidence_ref, intent=intent, origin=origin)

    @app.tool()
    def memory_unlink(source_id: str, target_id: str, relation: str = "related") -> dict:
        """Remove a connection without deleting either memory."""
        return vault.unlink(source_id, target_id, relation)

    @app.tool()
    def memory_enrichment_gate(memory_id: str) -> dict:
        """Check the author-owned region, without re-triggering machine output."""
        return vault.enrichment_gate(memory_id)

    @app.tool()
    def memory_enrich(memory_id: str, content: str,
                      expected_author_hash: str) -> dict:
        """Store an AI-owned enrichment after a hash-based concurrency gate."""
        return vault.enrich(memory_id, content, expected_author_hash)

    @app.tool()
    def memory_graph_projection(limit: int = 200) -> dict:
        """Build bounded in-memory graph projection; not verified evidence."""
        return vault.graph_projection(limit)

    @app.tool()
    def memory_neighborhood(memory_id: str, depth: int = 1, limit: int = 100) -> dict:
        """Explore nearby nodes and relations to reconstruct task context."""
        return vault.neighbors(memory_id, depth, limit)

    @app.tool()
    def memory_context(query: str, max_chars: int = 10000,
                       source_grounded_only: bool = False,
                       scope: str = "default", as_of: str | None = None) -> dict:
        """Legacy notes are explicitly unreviewed; strict evidence mode is opt-in."""
        return trust_context(vault, evidence, query, max_chars,
                             source_grounded_only=source_grounded_only,
                             scope=scope, as_of=as_of,
                             git_guard=git_guard)

    @app.tool()
    def memory_source_grounded_context(query: str, scope: str = "default",
                                       as_of: str | None = None,
                                       max_chars: int = 10000) -> dict:
        """Strict source-matched context without unreviewed memories or inferred truth."""
        return trust_context(vault, evidence, query, max_chars,
                             source_grounded_only=True, scope=scope, as_of=as_of)

    @app.tool()
    def memory_git_anchor(memory_id: str, repo_alias: str, relative_path: str) -> dict:
        """Pin a memory to an allowlisted clean committed Git blob; never assert truth."""
        return git_guard.anchor(memory_id, repo_alias, relative_path)

    @app.tool()
    def memory_git_status(memory_id: str) -> dict:
        """Read live Git drift status of a memory's file anchors."""
        return git_guard.status(memory_id)

    @app.tool()
    def memory_git_scan(invalidate_stale: bool = False, limit: int = 100) -> dict:
        """Find drift; optionally mark affected memories and descendants stale."""
        return git_guard.scan(invalidate=invalidate_stale, limit=limit)

    @app.tool()
    def memory_revise(memory_id: str, body: str, title: str | None = None,
                      valid_from: str | None = None,
                      valid_to: str | None = None) -> dict:
        """Revise a source memory, its known validity, and stale its derived descendants."""
        return vault.revise(memory_id, body, title,
                            valid_from=valid_from, valid_to=valid_to)

    @app.tool()
    def memory_invalidate(memory_id: str, reason: str = "Source no longer verified") -> dict:
        """Cascade stale status to downstream conclusions without erasing history."""
        return vault.invalidate(memory_id, reason)

    @app.tool()
    def memory_archive(memory_id: str) -> dict:
        """Hide a memory; encrypted event history retains it."""
        return vault.archive(memory_id)

    @app.tool()
    def memory_status() -> dict:
        """Check dual encrypted journals, record count, and replica separation."""
        return vault.status()

    @app.tool()
    def memory_evidence_source_add(title: str, json_document: str,
                                   scope: str = "default",
                                   observed_at: str | None = None) -> dict:
        """Store structured source JSON in the encrypted journal; NOT proof of truth."""
        return evidence.add_source(title, json_document, scope=scope,
                                   observed_at=observed_at)

    @app.tool()
    def memory_evidence_propose(fact_key: str, source_id: str, pointer: str,
                                scope: str = "default",
                                valid_from: str | None = None,
                                valid_to: str | None = None,
                                stale_after: str | None = None) -> dict:
        """Bind an unreviewed claim to an exact source JSON pointer. No truth promotion."""
        return evidence.propose(fact_key, source_id, pointer, scope=scope,
                                valid_from=valid_from, valid_to=valid_to,
                                stale_after=stale_after)

    @app.tool()
    def memory_evidence_reject(claim_id: str, reason: str) -> dict:
        """Persist a rejection tombstone and invalidate the claim and descendants."""
        return evidence.reject(claim_id, reason)

    @app.tool()
    def memory_evidence_context(query: str = "", scope: str = "default",
                                as_of: str | None = None, limit: int = 20) -> dict:
        """Only source-matched observations; conflicting or stale facts are withheld."""
        return evidence.query(query, scope=scope, as_of=as_of, limit=limit)

    @app.tool()
    def memory_briefing(project: str, at: str | None = None,
                        limit: int = 20, max_chars: int = 12_000,
                        include_evidence: bool = True) -> dict:
        """Scoped current constraints, work and source-matched observations.

        Project tags and evidence scope are organizational filters, NOT ACLs.
        No source match is proof of factual truth. No plaintext index is used.
        """
        return briefings.briefing(project, at=at, limit=limit,
                                  max_chars=max_chars,
                                  include_evidence=include_evidence)

    @app.tool()
    def memory_by_source(project: str, source_ref: str,
                         limit: int = 20, max_chars: int = 12_000) -> dict:
        """Find note cards by an exact stored source label, without filesystem reads.

        Stale records are marked; source labels are NOT Git-verified evidence.
        """
        return briefings.by_source(project, source_ref,
                                   limit=limit, max_chars=max_chars)

    # Explicit opt-in: peer registry is private local cached metadata, never
    # a default network crawler or a trusted source of executable instructions.
    import os
    peer_db = os.environ.get("NSL_PEER_DB")
    if peer_db:
        import sqlite3
        from pathlib import Path
        from .peer_bridge import PeerError, search_skills, read_skill

        @app.tool()
        def peer_skill_search(query: str, limit: int = 10) -> list[dict]:
            """Read cached untrusted reviewed Skill metadata, no execution."""
            with sqlite3.connect(
                "file:" + str(Path(peer_db).resolve()) + "?mode=ro", uri=True
            ) as db:
                return search_skills(db, query, limit)

        @app.tool()
        def peer_skill_get(name: str, version: str | None = None) -> dict:
            """Explicit retrieval with SHA-256 and size check. Never auto-apply."""
            with sqlite3.connect(
                "file:" + str(Path(peer_db).resolve()) + "?mode=ro", uri=True
            ) as db:
                entries = [e for e in search_skills(db, "", 50)
                           if e["name"] == name
                           and (version is None or e["version"] == version)]
            if len(entries) != 1:
                raise PeerError("no active matching Skill in local peer cache")
            return read_skill(entries[0])

    app.run(transport="stdio")

