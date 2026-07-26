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
        lines = [
            item.get("line")
            for item in requested
            if isinstance(item, dict) and isinstance(item.get("line"), int)
        ] if isinstance(requested, list) else []
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
                    }
                    for line in lines
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
