# Setup

Requirements:

- Python 3.11 or newer
- A DAP adapter
- A debuggable build with matching source and symbols

Run from the repository root so `aidbg` and `adapters/` resolve without
installation. Set `AIDBG_NETCOREDBG` to an explicit NetCoreDbg executable when
automatic discovery fails.

Each invocation creates a unique `.aidbg/sessions/` directory unless
`--trace-dir` is supplied. Do not share an explicit trace directory between
agents. Defaults are 30 seconds per DAP request, 120 seconds waiting for target
execution, 3 seconds for cleanup, and a 24-hour hard session lease. Override
them with `--request-timeout`, `--execution-timeout`, `--shutdown-timeout`, and
`--session-timeout`.

Adapter profiles contain executable candidates, adapter arguments, initialize
arguments, and launch defaults. Add another debugger by creating a JSON profile
under `adapters/`; do not add adapter details to `SKILL.md`.
