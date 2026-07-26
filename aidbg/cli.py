"""Interactive agent-facing DAP command line."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import threading
import traceback

from aidbg.commands import Breakpoint, parse_breakpoint, tokenize
from aidbg.lifecycle import SessionLimits
from aidbg.profile import AdapterProfile
from aidbg.protocol import JsonObject, JsonValue
from aidbg.session import DebugSession, InvalidVariableReferenceError


HELP = (
    "break FILE:LINE [if EXPR] | launch PROGRAM [--cwd DIR] [--args ...] | "
    "continue [--wait S] | wait [--timeout S] | next [--wait S] | "
    "stack [N] | scopes [--frame ID] | "
    "locals [N] [--frame ID] [--output FILE] | "
    "variables REF [N] [--output FILE] | "
    "eval [--frame ID] EXPR | status | stop | quit"
)


async def run(
    profile_path: Path,
    trace_directory: Path,
    limits: SessionLimits,
    session_timeout: float,
    verbose: bool,
) -> int:
    """Run one persistent interactive debugger session."""
    profile = AdapterProfile.load(profile_path)
    session = await DebugSession.create(
        profile,
        trace_directory,
        limits,
        verbose=verbose,
    )
    lease = HardSessionLease(session, session_timeout)
    lease.start()
    emit(
        {
            "ok": True,
            "adapter": profile.adapter_id,
            "state": "idle",
            "traceDirectory": str(trace_directory.resolve()),
        }
    )
    try:
        while True:
            try:
                line = input("aidbg> ").strip()
            except EOFError:
                line = "quit"
            if not line:
                continue
            try:
                if await execute(session, line):
                    await session.close()
                    emit(
                        {
                            "ok": True,
                            **session.cleanup_receipt(),
                        }
                    )
                    return 0
            except Exception as error:
                record_error(trace_directory, error)
                payload: JsonObject = {
                    "ok": False,
                    "error": (
                        error.code
                        if isinstance(error, InvalidVariableReferenceError)
                        else type(error).__name__
                    ),
                    "message": str(error),
                    "traceDirectory": str(trace_directory.resolve()),
                }
                if isinstance(error, InvalidVariableReferenceError):
                    payload["stopId"] = session.status()["stopId"]
                emit(payload)
    finally:
        lease.cancel()
        await session.close()


async def execute(session: DebugSession, line: str) -> bool:
    """Execute one REPL command; return true when the session should exit."""
    tokens = tokenize(line)
    if not tokens:
        return False
    command = tokens[0].lower()
    arguments = tokens[1:]

    if command == "help":
        emit({"ok": True, "commands": HELP})
    elif command == "break":
        if not arguments:
            raise ValueError("usage: break FILE:LINE [if EXPR]")
        breakpoint = parse_breakpoint(arguments[0])
        if len(arguments) > 1:
            if arguments[1].lower() != "if" or len(arguments) < 3:
                raise ValueError("usage: break FILE:LINE [if EXPR]")
            breakpoint = Breakpoint(
                breakpoint.file,
                breakpoint.line,
                " ".join(arguments[2:]),
            )
        await session.add_breakpoint(breakpoint)
        emit(
            {
                "ok": True,
                "breakpoint": f"{breakpoint.file}:{breakpoint.line}",
                "condition": breakpoint.condition,
            }
        )
    elif command == "launch":
        program, cwd, target_arguments = parse_launch(arguments)
        emit({"ok": True, **await session.launch(program, cwd, target_arguments)})
    elif command == "continue":
        wait_seconds = parse_timeout_option(
            arguments,
            "--wait",
            "continue [--wait SECONDS]",
        )
        emit(
            {
                "ok": True,
                **await session.continue_execution(wait_seconds),
            }
        )
    elif command == "wait":
        wait_seconds = parse_timeout_option(
            arguments,
            "--timeout",
            "wait [--timeout SECONDS]",
        )
        emit({"ok": True, **await session.wait_for_stop(wait_seconds)})
    elif command == "next":
        wait_seconds = parse_timeout_option(
            arguments,
            "--wait",
            "next [--wait SECONDS]",
        )
        emit({"ok": True, **await session.next(wait_seconds)})
    elif command == "stack":
        count = parse_count(arguments, 10)
        emit(
            {
                "ok": True,
                "stopId": session.stop_id,
                "frames": await session.stack(count),
            }
        )
    elif command == "scopes":
        frame_id = parse_frame_option(arguments)
        emit(
            {
                "ok": True,
                "stopId": session.stop_id,
                "scopes": await session.scopes(frame_id),
            }
        )
    elif command == "locals":
        local_arguments, output_path = parse_output_option(arguments)
        count, frame_id = parse_bounded_frame_options(local_arguments, 50)
        variables = await session.locals(count, frame_id)
        emit_or_export(
            {
                "ok": True,
                "stopId": session.stop_id,
                "variables": variables,
            },
            output_path,
            len(variables),
        )
    elif command == "variables":
        variable_arguments, output_path = parse_output_option(arguments)
        if not variable_arguments or len(variable_arguments) > 2:
            raise ValueError("usage: variables REFERENCE [COUNT]")
        reference = int(variable_arguments[0])
        count = (
            int(variable_arguments[1])
            if len(variable_arguments) > 1
            else 50
        )
        variables = await session.variables(reference, count)
        emit_or_export(
            {
                "ok": True,
                "stopId": session.stop_id,
                "variables": variables,
            },
            output_path,
            len(variables),
        )
    elif command == "eval":
        expression = line.partition(" ")[2].strip()
        if not expression:
            raise ValueError("usage: eval EXPRESSION")
        evaluation_frame_id: int | None = None
        frame_match = re.fullmatch(r"--frame\s+(\d+)\s+(.+)", expression)
        if frame_match:
            evaluation_frame_id = int(frame_match.group(1))
            expression = frame_match.group(2)
        emit(
            {
                "ok": True,
                "stopId": session.stop_id,
                "evaluation": await session.evaluate(
                    expression,
                    evaluation_frame_id,
                ),
            }
        )
    elif command == "status":
        emit({"ok": True, **session.status()})
    elif command == "stop":
        await session.stop()
        emit({"ok": True, **session.status()})
    elif command in {"quit", "exit"}:
        return True
    else:
        raise ValueError(f"unknown command {command!r}; use help")
    return False


def parse_launch(arguments: list[str]) -> tuple[Path, Path, list[str]]:
    """Parse launch arguments."""
    if not arguments:
        raise ValueError("usage: launch PROGRAM [--cwd DIR] [--args ...]")
    program = Path(arguments[0])
    cwd = program.parent if program.parent != Path() else Path.cwd()
    target_arguments: list[str] = []
    index = 1
    while index < len(arguments):
        option = arguments[index]
        if option == "--cwd" and index + 1 < len(arguments):
            cwd = Path(arguments[index + 1])
            index += 2
        elif option == "--args":
            target_arguments = arguments[index + 1 :]
            break
        else:
            raise ValueError(f"unknown launch option {option!r}")
    return program, cwd, target_arguments


def parse_count(arguments: list[str], default: int) -> int:
    """Parse an optional positive count."""
    count = int(arguments[0]) if arguments else default
    if count < 1:
        raise ValueError("count must be positive")
    return count


def parse_timeout_option(
    arguments: list[str],
    option: str,
    usage: str,
) -> float | None:
    """Parse one optional positive timeout."""
    if not arguments:
        return None
    if len(arguments) != 2 or arguments[0] != option:
        raise ValueError(f"usage: {usage}")
    timeout = float(arguments[1])
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    return timeout


def parse_output_option(
    arguments: list[str],
) -> tuple[list[str], Path | None]:
    """Remove one optional ``--output FILE`` argument."""
    positions = [
        index for index, argument in enumerate(arguments) if argument == "--output"
    ]
    if not positions:
        return arguments, None
    if len(positions) != 1:
        raise ValueError("--output may be specified once")
    index = positions[0]
    if index + 1 >= len(arguments):
        raise ValueError("--output requires a file")
    return (
        arguments[:index] + arguments[index + 2 :],
        Path(arguments[index + 1]),
    )


def parse_frame_option(arguments: list[str]) -> int | None:
    """Parse an optional ``--frame ID``."""
    if not arguments:
        return None
    if len(arguments) != 2 or arguments[0] != "--frame":
        raise ValueError("usage: scopes [--frame ID]")
    return int(arguments[1])


def parse_bounded_frame_options(
    arguments: list[str],
    default_count: int,
) -> tuple[int, int | None]:
    """Parse optional count and frame arguments."""
    count = default_count
    frame_id: int | None = None
    index = 0
    if arguments and arguments[0] != "--frame":
        count = parse_count(arguments[:1], default_count)
        index = 1
    if index < len(arguments):
        if len(arguments) != index + 2 or arguments[index] != "--frame":
            raise ValueError("usage: locals [COUNT] [--frame ID]")
        frame_id = int(arguments[index + 1])
    return count, frame_id


def emit(value: JsonValue) -> None:
    """Write one compact model-visible result."""
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def emit_or_export(
    payload: JsonObject,
    output_path: Path | None,
    count: int,
) -> None:
    """Emit a result or write it to a file and emit only a compact receipt."""
    if output_path is None:
        emit(payload)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    output_path.write_text(f"{serialized}\n", encoding="utf-8")
    emit(
        {
            "ok": True,
            "stopId": payload.get("stopId"),
            "outputFile": str(output_path.resolve()),
            "bytes": len(serialized.encode("utf-8")) + 1,
            "count": count,
        }
    )


def record_error(trace_directory: Path, error: BaseException) -> None:
    """Append full CLI errors outside the model-visible output."""
    trace_directory.mkdir(parents=True, exist_ok=True)
    with (trace_directory / "errors.log").open("a", encoding="utf-8") as stream:
        traceback.print_exception(error, file=stream)


def default_trace_directory() -> Path:
    """Return a collision-resistant per-process trace directory."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return Path(
        ".aidbg",
        "sessions",
        f"{timestamp}-{os.getpid()}-{secrets.token_hex(4)}",
    )


class HardSessionLease:
    """Force cleanup and process exit when a CLI session exceeds its lease."""

    def __init__(self, session: DebugSession, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError("session timeout must be positive")
        self._session = session
        self._timeout = timeout
        self._cancelled = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="aidbg-hard-session-lease",
            daemon=True,
        )

    def start(self) -> None:
        """Start the hard lease."""
        self._thread.start()

    def cancel(self) -> None:
        """Disarm the lease."""
        self._cancelled.set()

    def _run(self) -> None:
        if self._cancelled.wait(self._timeout):
            return
        self._session.force_close()
        receipt = self._session.cleanup_receipt()
        payload = json.dumps(
            {
                "ok": False,
                "error": "SessionTimeout",
                "message": f"hard session timeout after {self._timeout:g}s",
                **receipt,
            },
            separators=(",", ":"),
        )
        try:
            os.write(1, f"\n{payload}\n".encode())
        finally:
            os._exit(124)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Compact interactive DAP client")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--execution-timeout", type=float, default=120)
    parser.add_argument("--shutdown-timeout", type=float, default=3)
    parser.add_argument("--session-timeout", type=float, default=24 * 60 * 60)
    parser.add_argument("-v", "--verbose", action="store_true")
    arguments = parser.parse_args()
    trace_directory = arguments.trace_dir or default_trace_directory()
    limits = SessionLimits(
        request_seconds=arguments.request_timeout,
        execution_seconds=arguments.execution_timeout,
        shutdown_seconds=arguments.shutdown_timeout,
    )
    try:
        exit_code = asyncio.run(
            run(
                arguments.profile,
                trace_directory,
                limits,
                arguments.session_timeout,
                arguments.verbose,
            )
        )
    except Exception as error:
        record_error(trace_directory, error)
        emit(
            {
                "ok": False,
                "error": type(error).__name__,
                "message": str(error),
                "traceDirectory": str(trace_directory.resolve()),
            }
        )
        raise SystemExit(1) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
