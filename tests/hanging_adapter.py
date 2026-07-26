"""DAP adapter fixture that stops responding after initialization."""

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parents[1]))

from aidbg.protocol import JsonObject, read_message, write_message

sequence = 0
request = read_message(sys.stdin.buffer)
sequence += 1
response: JsonObject = {
    "seq": sequence,
    "type": "response",
    "request_seq": request["seq"],
    "command": request["command"],
    "success": True,
    "body": {},
}
write_message(sys.stdout.buffer, response)

read_message(sys.stdin.buffer)
time.sleep(60)
