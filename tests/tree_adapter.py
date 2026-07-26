"""DAP adapter fixture that owns a long-running child process."""

from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).parents[1]))

from aidbg.protocol import JsonObject, read_message, write_message

pid_path = Path(sys.argv[1])
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
)
pid_path.write_text(str(child.pid), encoding="ascii")

sequence = 0


def respond(request: JsonObject) -> None:
    global sequence
    sequence += 1
    write_message(
        sys.stdout.buffer,
        {
            "seq": sequence,
            "type": "response",
            "request_seq": request["seq"],
            "command": request["command"],
            "success": True,
            "body": {},
        },
    )


try:
    while True:
        request = read_message(sys.stdin.buffer)
        if request["command"] == "initialize":
            respond(request)
        else:
            time.sleep(60)
finally:
    if child.poll() is None:
        child.kill()
    child.wait(timeout=2)
