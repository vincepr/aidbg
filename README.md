# aidbg

`aidbg` is a small, agent-facing DAP CLI. It owns one debug adapter process,
keeps protocol traffic in a trace, and returns bounded JSON results suitable for
model context. Adapter profiles keep the command surface debugger-independent.

## Run

Python 3.11 or newer and a DAP adapter are required.

```text
python -m pip install -e .
aidbg --profile adapters/netcoredbg.json
```

Set `AIDBG_NETCOREDBG` when NetCoreDbg is not auto-discovered. In the REPL, run
`help`; the bundled [skill](skills/aidbg-debug/SKILL.md) contains the concise
agent workflow and defers setup details until needed.

Each invocation owns an isolated adapter process tree and trace directory.
Operations are bounded, the session has a 24-hour hard lease, and shutdown emits
a cleanup receipt. Run a separate invocation per parallel agent.

## Verify

```text
python -m unittest discover -s tests -v
python -m mypy aidbg tests
```

Design decisions are recorded in [docs/adr](docs/adr).
