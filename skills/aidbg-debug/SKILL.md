---
name: aidbg-debug
description: Debug runtime failures through the compact, debugger-independent aidbg DAP CLI.
---

# aidbg Debug

Run a fresh, isolated process for each target or build variant and agent:

```powershell
python -m aidbg.cli --profile adapters/netcoredbg.json
```

Commands:

```text
break FILE:LINE [if EXPR]
launch PROGRAM [--cwd DIR] [--args ...]
continue [--wait SECONDS] | wait [--timeout SECONDS] | next [--wait SECONDS]
stack [COUNT] | scopes [--frame ID] | locals [COUNT] [--frame ID] [--output FILE]
variables REF [COUNT] [--output FILE] | eval [--frame ID] EXPR
status | stop | quit
```

Build with matching symbols and set the earliest useful breakpoint before
`launch`. Keep inspection focused. Use `--verbose` only for bounded extra stop
context and `--output` for data that should not enter model context.

DAP frame and variable references expire on `continue` or `next`; reacquire
them from the new stop. A wait timeout leaves the target running; call `wait`
again or `stop`. `variables` expansion and `eval` can execute target code,
including getters; inspect backing fields or counters first.

Stop once runtime evidence distinguishes the root cause. Run `stop`, then
`quit`; verify the cleanup receipt. Full DAP traffic and errors remain in the
reported trace directory. Read [setup.md](references/setup.md) only when the
adapter or prerequisites are unavailable. For NetCoreDbg-specific symbol or
evaluator failures, read [netcoredbg.md](references/netcoredbg.md).
