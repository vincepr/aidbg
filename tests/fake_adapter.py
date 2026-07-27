"""Small DAP adapter used by integration tests."""

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parents[1]))

from aidbg.protocol import JsonObject, read_message, write_message

sequence = 0
pending_launch: JsonObject | None = None
continue_delay = float(sys.argv[1]) if len(sys.argv) > 1 else 0
source_path = sys.argv[2] if len(sys.argv) > 2 else "Fixture.cs"
breakpoint_mode = sys.argv[3] if len(sys.argv) > 3 else "verified"
breakpoint_events: list[JsonObject] = []


def send(message: JsonObject) -> None:
    global sequence
    sequence += 1
    message["seq"] = sequence
    write_message(sys.stdout.buffer, message)


def respond(request: JsonObject, body: JsonObject | None = None) -> None:
    send(
        {
            "type": "response",
            "request_seq": request["seq"],
            "command": request["command"],
            "success": True,
            "body": body or {},
        }
    )


while True:
    request = read_message(sys.stdin.buffer)
    command = request["command"]
    if command == "initialize":
        respond(request, {"supportsConfigurationDoneRequest": True})
    elif command == "launch":
        pending_launch = request
        send({"type": "event", "event": "initialized", "body": {}})
    elif command == "setBreakpoints":
        arguments = request.get("arguments")
        requested = (
            arguments.get("breakpoints")
            if isinstance(arguments, dict)
            else None
        )
        lines: list[int] = []
        if isinstance(requested, list):
            for item in requested:
                line = item.get("line") if isinstance(item, dict) else None
                if isinstance(line, int):
                    lines.append(line)
        source = (
            arguments.get("source")
            if isinstance(arguments, dict)
            else None
        )
        breakpoint_ids: list[int] = []
        if breakpoint_mode in {"changed", "removed"}:
            for line in lines:
                breakpoint_id = len(breakpoint_events) + 1
                breakpoint_ids.append(breakpoint_id)
                breakpoint_events.append(
                    {
                        "reason": breakpoint_mode,
                        "breakpoint": {
                            "verified": breakpoint_mode == "changed",
                            "id": breakpoint_id,
                            "line": line + 1,
                            "source": source if isinstance(source, dict) else {},
                        },
                    }
                )
        respond(
            request,
            {
                "breakpoints": [
                    {
                        "verified": breakpoint_mode == "verified",
                        "line": line,
                        **(
                            {"message": "pending test binding"}
                            if breakpoint_mode != "verified"
                            else {}
                        ),
                        **(
                            {"id": breakpoint_ids[index]}
                            if breakpoint_mode in {"changed", "removed"}
                            else {}
                        ),
                    }
                    for index, line in enumerate(lines)
                ]
            },
        )
    elif command == "setExceptionBreakpoints":
        respond(request)
    elif command == "configurationDone":
        respond(request)
        if pending_launch is None:
            raise RuntimeError("configurationDone before launch")
        respond(pending_launch)
        pending_launch = None
        for breakpoint_event in breakpoint_events:
            send(
                {
                    "type": "event",
                    "event": "breakpoint",
                    "body": breakpoint_event,
                }
            )
        send(
            {
                "type": "event",
                "event": "stopped",
                "body": {"reason": "breakpoint", "threadId": 1},
            }
        )
    elif command == "stackTrace":
        respond(
            request,
            {
                "stackFrames": [
                    {
                        "id": 100,
                        "name": "Fixture.Run",
                        "line": 27,
                        "column": 1,
                        "source": {"name": "Fixture.cs", "path": source_path},
                    }
                ]
            },
        )
    elif command == "scopes":
        respond(
            request,
            {
                "scopes": [
                    {
                        "name": "Locals",
                        "variablesReference": 10,
                        "expensive": False,
                    }
                ]
            },
        )
    elif command == "variables":
        arguments = request.get("arguments")
        reference = (
            arguments.get("variablesReference")
            if isinstance(arguments, dict)
            else None
        )
        if reference != 10:
            send(
                {
                    "type": "response",
                    "request_seq": request["seq"],
                    "command": command,
                    "success": False,
                    "message": "0x80004005",
                }
            )
            continue
        respond(
            request,
            {
                "variables": [
                    {
                        "name": "task",
                        "value": "docs",
                        "type": "string",
                        "variablesReference": 0,
                    }
                ]
            },
        )
    elif command == "evaluate":
        arguments = request.get("arguments")
        frame_id = arguments.get("frameId") if isinstance(arguments, dict) else None
        respond(
            request,
            {
                "result": "docs",
                "variablesReference": 0,
                "frameId": frame_id,
            },
        )
    elif command == "continue":
        respond(request, {"allThreadsContinued": True})
        time.sleep(continue_delay)
        send({"type": "event", "event": "terminated", "body": {}})
    elif command == "disconnect":
        respond(request)
        break
    else:
        send(
            {
                "type": "response",
                "request_seq": request["seq"],
                "command": command,
                "success": False,
                "message": "unsupported test request",
            }
        )
