# Setup

Requirements:

- Python 3.11 or newer
- A DAP adapter
- A debuggable build with matching source and symbols

Run from the repository root so `aidbg` and `adapters/` resolve without
installation. Set `AIDBG_NETCOREDBG` to an explicit NetCoreDbg executable when
automatic discovery fails.

Adapter profiles contain executable candidates, adapter arguments, initialize
arguments, and launch defaults. Add another debugger by creating a JSON profile
under `adapters/`; do not add adapter details to `SKILL.md`.
