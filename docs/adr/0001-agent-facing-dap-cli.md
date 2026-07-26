# 0001: Agent-facing DAP CLI

Status: Accepted

## Decision

Expose a small persistent CLI plus a concise skill, backed by standard DAP and
JSON adapter profiles. Do not expose one MCP tool per DAP operation or require
agents to sequence raw DAP messages.

Return compact stop evidence by default, bounded extra context with `--verbose`,
and file receipts for bulk `locals` or `variables` output. Preserve expression
text verbatim and surface breakpoint binding status.

## Consequences

The interface stays debugger-independent and avoids permanent MCP schema cost.
DAP traces retain full diagnostics without placing them in model context.
Adapter-specific setup belongs in profiles or optional skill references.
