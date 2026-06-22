# ADR-003: Claude Agent SDK over manual tool loop

**Status:** Accepted (Day 4)

## Context

The orchestration layer needs to drive a multi-step clinical workflow:
read patient data, search guidelines, propose observations. Options:

- **Direct Anthropic SDK (`messages.create`) + manual tool loop**: full control,
  but we implement the tool dispatch loop, session management, and concurrency.
- **Claude Agent SDK**: same agent loop as Claude Code, built-in hooks, subagents,
  session management.
- **Third-party frameworks** (LangChain, LlamaIndex, CrewAI): broader ecosystem,
  but adds abstraction over systems already well-abstracted.

## Decision

Claude Agent SDK (`claude-agent-sdk>=0.1`) with three subagents.

## Rationale

**Built-in hooks.** The `PostToolUse` hook fires after every tool call and gives
us the tool name, input, and output. We use this to append to the audit chain
and track per-call latency and token cost — with no instrumentation in the tool
implementations themselves.

**Subagent pattern maps naturally.** Reader/RAG/Proposal are conceptually distinct
agents with different tool sets and system prompts. The Agent SDK's `agents={}` 
config makes this explicit and testable.

**Session management for long workflows.** `resume=session_id` lets the orchestrator
continue a workflow across multiple calls without re-reading patient data already
in context.

**No third-party framework.** LangChain and LlamaIndex add abstraction layers with
frequent breaking changes. The Agent SDK wraps Claude Code's proven agent loop
directly, with a stable interface.

**Alignment with the Anthropic stack.** This project is explicitly built on the
Anthropic ecosystem. The Agent SDK, MCP server, and Anthropic SDK are designed
to compose.

## Consequences

- Tighter coupling to Anthropic. Acceptable: the project is a reference
  implementation for the Anthropic stack, not a multi-provider abstraction.
- `claude-agent-sdk` requires `claude` CLI installed and API key set.
  `ANTHROPIC_API_KEY` env var must be present at runtime.
- The orchestrator lives in `src/clinical_agent/` (separate package from
  `src/fhir_mcp/`) to preserve the MCP server as an independently deployable unit.
