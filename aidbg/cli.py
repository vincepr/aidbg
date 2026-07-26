"""Interactive agent-facing DAP command line."""

import argparse
import asyncio
import json
from pathlib import Path
import traceback

from aidbg.commands import Breakpoint, parse_breakpoint, tokenize
from aidbg.profile import AdapterProfile
from aidbg.protocol import JsonValue
from aidbg.session import DebugSession


HELP = (
    "break FILE:LINE [if EXPR] | launch PROGRAM [--cwd DIR] [--args ...] | "
    "continue | next | stack [N] | scopes | locals [N] | "
    "variables REF [N] | eval EXPR | status | stop | quit"
)


async def run(profile_path: Path, trace_directory: Path) -> int:
    """Run one persistent interactive debugger session."""
    profile = AdapterProfile.load(profile_path)
    session = await DebugSession.create(profile, trace_directory)
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
                    return 0
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
    finally:
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
        emit({"ok": True, **await session.continue_execution()})
    elif command == "next":
        emit({"ok": True, **await session.next()})
    elif command == "stack":
        count = parse_count(arguments, 10)
        emit({"ok": True, "frames": await session.stack(count)})
    elif command == "scopes":
        emit({"ok": True, "scopes": await session.scopes()})
    elif command == "locals":
        count = parse_count(arguments, 50)
        emit({"ok": True, "variables": await session.locals(count)})
    elif command == "variables":
        if not arguments:
            raise ValueError("usage: variables REFERENCE [COUNT]")
        reference = int(arguments[0])
        count = int(arguments[1]) if len(arguments) > 1 else 50
        emit(
            {
                "ok": True,
                "variables": await session.variables(reference, count),
            }
        )
    elif command == "eval":
        expression = line.partition(" ")[2].strip()
        if not expression:
            raise ValueError("usage: eval EXPRESSION")
        emit({"ok": True, "evaluation": await session.evaluate(expression)})
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


def emit(value: JsonValue) -> None:
    """Write one compact model-visible result."""
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def record_error(trace_directory: Path, error: BaseException) -> None:
    """Append full CLI errors outside the model-visible output."""
    trace_directory.mkdir(parents=True, exist_ok=True)
    with (trace_directory / "errors.log").open("a", encoding="utf-8") as stream:
        traceback.print_exception(error, file=stream)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Compact interactive DAP client")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=Path(".aidbg", "sessions", "latest"),
    )
    arguments = parser.parse_args()
    try:
        exit_code = asyncio.run(run(arguments.profile, arguments.trace_dir))
    except Exception as error:
        record_error(arguments.trace_dir, error)
        emit(
            {
                "ok": False,
                "error": type(error).__name__,
                "message": str(error),
                "traceDirectory": str(arguments.trace_dir.resolve()),
            }
        )
        raise SystemExit(1) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
