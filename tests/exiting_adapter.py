"""DAP adapter that rejects one request and then exits."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from aidbg.protocol import JsonObject, read_message, write_message


def respond(
    request: JsonObject,
    *,
    success: bool,
    message: str | None = None,
) -> None:
    response: JsonObject = {
        "seq": request["seq"],
        "type": "response",
        "request_seq": request["seq"],
        "command": request["command"],
        "success": success,
    }
    if message is not None:
        response["message"] = message
    write_message(sys.stdout.buffer, response)


initialize = read_message(sys.stdin.buffer)
respond(initialize, success=True)
rejected = read_message(sys.stdin.buffer)
respond(rejected, success=False, message="test rejection")
raise SystemExit(23)
