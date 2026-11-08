"""MCP stdio adapter; no network listener and no private Noosphere dependencies."""
from .vault import MemoryVault

def run(vault: MemoryVault):
    try:
        try:
            from mcp.server.mcpserver import MCPServer as MCPApp  # MCP SDK 2.x
        except ImportError:
            from mcp.server.fastmcp import FastMCP as MCPApp  # MCP SDK 1.x
    except ImportError as e:
        raise RuntimeError("Install dependencies: pip install -e .") from e
    app = MCPApp("noosphere-lite-mcp")

    @app.tool()
    def memory_add(title: str, body: str, tags: list[str] | None = None,
                   kind: str = "note", source: str = "",
                   valid_from: str | None = None,
                   valid_to: str | None = None,
                   observed_at: str | None = None) -> dict:
        """Persist dated memory: recorded_at is automatic; validity is explicitly sourced."""
        return vault.add(title, body, tags, kind, source,
                         valid_from=valid_from, valid_to=valid_to, observed_at=observed_at)

    @app.tool()
    def memory_search(query: str, limit: int = 10,
                      as_of: str | None = None) -> list[dict]:
        """Find memories, optionally filtering by explicitly known validity at an instant."""
        return vault.search(query, limit, as_of=as_of)

    @app.tool()
    def memory_suggest_links(memory_id: str, limit: int = 10) -> list[dict]:
        """Suggest candidate cross-domain links without creating or verifying them."""
        return vault.suggest_links(memory_id, limit)

    @app.tool()
    def memory_read(memory_id: str) -> dict:
        """Retrieve one specific memory's complete content."""
        return vault.read(memory_id)

    @app.tool()
    def memory_link(source_id: str, target_id: str, relation: str = "related") -> dict:
        """Add a typed, directed connection between two memories."""
        return vault.link(source_id, target_id, relation)

    @app.tool()
    def memory_unlink(source_id: str, target_id: str, relation: str = "related") -> dict:
        """Remove a connection without deleting either memory."""
        return vault.unlink(source_id, target_id, relation)

    @app.tool()
    def memory_neighborhood(memory_id: str, depth: int = 1, limit: int = 100) -> dict:
        """Explore nearby nodes and relations to reconstruct task context."""
        return vault.neighbors(memory_id, depth, limit)

    @app.tool()
    def memory_context(query: str, max_chars: int = 10000) -> dict:
        """Bring relevant long-term memories into a bounded working context."""
        return vault.context(query, max_chars)

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

    app.run(transport="stdio")

