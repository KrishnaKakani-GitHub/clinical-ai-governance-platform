# ADR-001: MCP over direct Anthropic API tool definitions

**Status:** Accepted

## Context

To expose clinical FHIR data to LLM agents, we needed to decide how to define
the tools Claude can call. Two approaches were viable:

- **Direct API tools**: define tool schemas inline in each `messages.create()` call.
  Simple, no extra infrastructure, schema lives in the calling code.
- **MCP server**: wrap tools in a FastMCP server over stdio (local) or SSE (remote).
  Adds a server process but decouples tool definitions from the caller.

## Decision

MCP server (FastMCP 3.x), stdio transport for local use, SSE for remote (Day 7).

## Rationale

**Transport-agnostic.** The same server works with Claude Code (stdio), the
Agent SDK (`mcp_servers` config), and claude.ai web connectors (SSE). Direct
API tools are tied to the calling SDK.

**Self-describing schemas.** FastMCP generates JSON schemas from Python type hints
and docstrings. Tool definitions stay with the implementation, not the caller.

**PHI boundary.** The MCP server is a controlled entry point: all data access
goes through a single process that enforces auth and audit. Direct API tools
scatter this responsibility across every caller.

**Portfolio reuse.** A portfolio company can connect to the server with zero
changes to the server code — only config (env vars, `claude mcp add`) changes.

**Claude Code compatibility.** Claude Code natively understands MCP. The server
shows up in `/mcp` and is inspectable with `npx @modelcontextprotocol/inspector`.

## Consequences

- An additional server process must run (launched by Claude Code as a subprocess).
- Overhead is negligible: the server is stateless and trivially restartable.
- Tests target `store.py` directly (not through MCP) because that's where the
  safety-critical logic lives. The MCP layer is thin wrapper — no business logic.
