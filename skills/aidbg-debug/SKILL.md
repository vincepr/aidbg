---
name: aidbg-debug
description: Debug runtime failures through the compact, debugger-independent aidbg DAP CLI.
---

# aidbg Debug

Start one isolated session per agent:

```powershell
python -m aidbg.cli --profile adapters/netcoredbg.json --trace-dir .aidbg/sessions/<id>
```

1. Build the target with matching symbols.
2. Add the earliest useful breakpoint before `launch`.
3. Use `stack`, then focused `locals`, `variables`, or `eval` commands.
4. Continue or step until evidence explains the root cause.
5. Run `stop`, then `quit`. Confirm no target or adapter remains.

Keep output bounded. Prefer focused expressions over broad traversal. Full DAP
traffic and exceptions stay in the reported trace directory; inspect those
files only when the compact error is insufficient.

Use `--frame ID` with `scopes`, `locals`, or `eval` when the value belongs to a
caller. If an adapter rejects lambdas or method-heavy expressions, use direct
property/index evaluation and follow `variablesReference` values. Stop once
runtime evidence decisively distinguishes the root cause from competing causes.

Run `help` for the command list. Read [setup.md](references/setup.md) only when
the adapter or prerequisites are unavailable.
