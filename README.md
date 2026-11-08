# Noosphere Lite MCP

Independent, Linux-native long-term memory for MCP-compatible AI agents.

**This is a new, separate implementation, not a reduced source dump or a parser for a private Noosphere deployment.** It shares general ideas (memory on demand, links, agent-independent state), not private storage layout, file tags, schemas, API routes, or decoding procedures.

## Features

- Store notes, decisions, tasks, observations, and source references.
- Text search with ranked results; retrieve full content by random ID only when needed.
- Typed, directed links and bounded 1–3-hop graph exploration.
- Retrieval into a bounded working context for the model.
- AES-256-GCM encrypted, append-only event journal with chained authenticated frames.
- Mirrored, integrity-checked, recoverable journal copies. Independent filesystem mountpoints required by default.
- Local MCP stdio interface: 9 tools, no HTTP listener, arbitrary file reads, code execution, or shell access.
- Synthetic tests only: no production data, credentials, private parsers, or network configurations.

## Install on Linux (Python 3.11+)

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -e .

Configure primary and mirror on distinct storage filesystems. A second folder on the same device is not a real backup:

    export NSL_PRIMARY=/mnt/storage-a/noosphere-lite
    export NSL_MIRROR=/mnt/storage-b/noosphere-lite
    export NSL_KEY_FILE=$HOME/.config/noosphere-lite/key
    python -m noosphere_lite init
    python -m noosphere_lite status

Initialization creates a private 32-byte local key file (0600) and two AES-GCM journals (0600). Data directories must be private (0700). Back up the key separately through an offline secure channel: losing every key copy permanently loses access to the vault. Same-user OS compromise can access the key; encryption does not protect against a compromised live agent or user session.

For a disposable demo on a single filesystem ONLY, add --development-same-device to commands, or set NSL_DEVELOPMENT_SAME_DEVICE=1. This bypasses redundancy requirements and is not acceptable for important data.

## MCP client

Start with python -m noosphere_lite mcp.

Example for an MCP host that accepts stdio server configuration:

    {
      "mcpServers": {
        "noosphere-lite": {
          "command": "/absolute/path/to/.venv/bin/python",
          "args": ["-m", "noosphere_lite", "mcp"],
          "env": {
            "NSL_PRIMARY": "/mnt/storage-a/noosphere-lite",
            "NSL_MIRROR": "/mnt/storage-b/noosphere-lite",
            "NSL_KEY_FILE": "/home/you/.config/noosphere-lite/key"
          }
        }
      }
    }

This is an MCP server, not automatically an installable ChatGPT custom GPT or OpenAI-hosted connector. Use with ChatGPT only through an authorized compatible MCP client/bridge. Never expose raw stdio or a vault over an unauthenticated public network endpoint.

## MCP tools

- memory_add: store a note or decision.
- memory_search: find relevant memories without full payloads.
- memory_read: retrieve one selected payload.
- memory_link and memory_unlink: typed relationships.
- memory_neighborhood: bounded navigation across connected memories.
- memory_context: assemble a compact task-specific context.
- memory_archive: hide from regular retrieval, retaining encrypted history.
- memory_status: integrity and replica status.

Search is local lexical retrieval, not local model inference, vector search, or autonomous semantic extraction. Relationships are explicitly entered, not automatically hallucinated.

## Architecture and security

On disk this uses a private-to-this-project NLV1 binary event stream, not a JSON graph, SQL table schema, or adapter for the owner's internal Noosphere. The entire event content is AES-256-GCM encrypted with unique per-frame nonces. Authentication binds each event to its sequence and preceding event digest. Random UUIDs do not embed host paths or private project identifiers.

The stream is decrypted only in local process memory. Search indices are transient; no plaintext content is written as a search cache. Ciphertext lengths, total file size and timing remain observable metadata.

Each journal is validated at read/write. If one copy is damaged or behind, a valid matching-prefix journal is mirrored to the other. Divergent histories fail closed. Cross-device writes cannot be atomically committed together; after a crash, the next successful open reconciles prefixes. If both copies are lost/corrupted, data may be lost. Two mirrored disks are not equivalent to offsite, immutable, versioned backups.

This is a single-host, single-writer design using flock; it is not a distributed database or a clustered multi-writer protocol. Mountpoints on different filesystems do not prove different physical disks if storage is virtualized. The maximum journal length is currently 150,000 events; benchmark before scaling up.

IMPORTANT: memory_archive only hides content from queries. Historical encrypted events are retained in the append-only journal. This is not a cryptographic erasure operation. Data deletion policies require a separate audited compaction, key rotation, and backup retention plan.

Do not commit encryption keys, private vault journals, production graph exports, tokens, internal Noosphere format documentation or infrastructure addresses.

## Tests

    python -m unittest discover -s tests -v

## Scope

Deliberately excludes proprietary storage formats, private graph translators, autonomous agent orchestration, internal source connectors, role escalation and automatic writes to host projects. This is a genuinely separate implementation with common high-level features, not compatibility with any private deployment.

Planned: stronger query ranking and measured search benchmarks, encrypting compaction, external key manager support, per-agent read-only permissions, offsite backup integration, and a verified client integration test.

## License

MIT; see LICENSE.

