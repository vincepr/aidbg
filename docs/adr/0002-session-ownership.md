# 0002: Session ownership and bounds

Status: Accepted

## Decision

One CLI invocation owns one adapter process tree, one target, and one unique
trace directory. DAP requests, execution waits, shutdown, and the complete
session are bounded. Cleanup always kills and reaps the owned tree and reports a
receipt.

Completed adapter sessions are not reused. Relaunch returns
`session_terminated`; start a new invocation. Parallel agents use separate
invocations and must not share an explicit trace directory.

## Consequences

There is no shared session registry or adapter-specific restart state. Crashes
surface as `adapter_exited` with exit code and trace path. An execution wait
timeout remains nonfatal so long-running target work can be observed again.
