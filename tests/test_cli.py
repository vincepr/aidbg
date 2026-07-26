import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from aidbg.cli import default_trace_directory


class CliTests(unittest.TestCase):
    def test_quit_exits_successfully_without_false_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory, "fake.json")
            profile.write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "commandCandidates": [sys.executable],
                        "arguments": [
                            str(Path(__file__).with_name("fake_adapter.py"))
                        ],
                        "initialize": {"adapterID": "fake"},
                        "launchDefaults": {},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aidbg.cli",
                    "--profile",
                    str(profile),
                    "--trace-dir",
                    str(Path(directory, "trace")),
                ],
                input="quit\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn('"ok":false', result.stdout)
            self.assertIn('"adapterReaped":true', result.stdout)

    def test_default_trace_directories_are_unique(self) -> None:
        first = default_trace_directory()
        second = default_trace_directory()

        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)

    def test_hard_session_timeout_exits_blocked_repl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory, "fake.json")
            profile.write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "commandCandidates": [sys.executable],
                        "arguments": [
                            str(Path(__file__).with_name("fake_adapter.py"))
                        ],
                        "initialize": {"adapterID": "fake"},
                        "launchDefaults": {},
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "aidbg.cli",
                    "--profile",
                    str(profile),
                    "--trace-dir",
                    str(Path(directory, "trace")),
                    "--session-timeout",
                    "0.5",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            started = time.monotonic()
            try:
                return_code = process.wait(timeout=5)
                output = process.stdout.read() if process.stdout else ""
            finally:
                if process.poll() is None:
                    process.kill()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

            self.assertEqual(124, return_code, output)
            self.assertLess(time.monotonic() - started, 4)
            self.assertIn('"error":"SessionTimeout"', output)

    def test_hard_timeout_reaps_adapter_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory, "child.pid")
            profile = Path(directory, "tree.json")
            profile.write_text(
                json.dumps(
                    {
                        "id": "tree",
                        "commandCandidates": [sys.executable],
                        "arguments": [
                            str(Path(__file__).with_name("tree_adapter.py")),
                            str(pid_path),
                        ],
                        "initialize": {"adapterID": "tree"},
                        "launchDefaults": {},
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "aidbg.cli",
                    "--profile",
                    str(profile),
                    "--trace-dir",
                    str(Path(directory, "trace")),
                    "--session-timeout",
                    "0.5",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(124, process.wait(timeout=5))
                child_pid = int(pid_path.read_text(encoding="ascii"))
            finally:
                if process.poll() is None:
                    process.kill()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

            deadline = time.monotonic() + 2
            while process_exists(child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(process_exists(child_pid))


def process_exists(process_id: int) -> bool:
    """Return whether a process still exists."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return ctypes.get_last_error() == 5
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    unittest.main()
