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
    def test_adapter_exit_uses_stable_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = write_profile(
                Path(directory),
                "exiting",
                "exiting_adapter.py",
            )
            result = run_cli(
                Path(directory),
                profile,
                "launch fixture.dll\nquit\n",
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn('"error":"adapter_exited"', result.stdout)
            self.assertIn("exit code 23", result.stdout)
            self.assertNotIn('"error":"OSError"', result.stdout)

    def test_relaunch_after_termination_has_stable_recovery_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_cli(
                root,
                write_profile(root),
                (
                    "launch fixture.dll\n"
                    "continue\n"
                    "launch fixture.dll\n"
                    "quit\n"
                ),
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn('"error":"session_terminated"', result.stdout)
            self.assertIn("start a new aidbg session", result.stdout)
            self.assertNotIn("already active", result.stdout)

    def test_break_condition_keeps_expression_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_cli(
                root,
                write_profile(root),
                (
                    'break Fixture.cs:27 if task.Name == "deploy"\n'
                    "launch fixture.dll\n"
                    "quit\n"
                ),
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                '"condition":"task.Name == \\"deploy\\""',
                result.stdout,
            )
            records = [
                json.loads(line)
                for line in Path(root, "trace", "dap.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            request = next(
                record["value"]
                for record in records
                if record["direction"] == "send"
                and isinstance(record["value"], dict)
                and record["value"].get("command") == "setBreakpoints"
            )
            self.assertEqual(
                'task.Name == "deploy"',
                request["arguments"]["breakpoints"][0]["condition"],
            )

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

    def test_wait_command_resumes_observing_a_running_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory, "fake.json")
            profile.write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "commandCandidates": [sys.executable],
                        "arguments": [
                            str(Path(__file__).with_name("fake_adapter.py")),
                            "0.2",
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
                    "--execution-timeout",
                    "0.05",
                ],
                input=(
                    "break Fixture.cs:27\n"
                    "launch fixture.dll\n"
                    "continue\n"
                    "wait --timeout 0.5\n"
                    "quit\n"
                ),
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn('"waitTimedOut":true', result.stdout)
            self.assertNotIn('"ok":false', result.stdout)
            self.assertIn('"reason":"terminated"', result.stdout)
            self.assertIn('"targetExited":true', result.stdout)
            self.assertIn('"processTreeClosed":true', result.stdout)

    def test_verbose_flag_adds_stop_stack_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "Fixture.cs")
            source.write_text(
                "".join(f"line {line}\n" for line in range(1, 31)),
                encoding="utf-8",
            )
            profile = Path(directory, "fake.json")
            profile.write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "commandCandidates": [sys.executable],
                        "arguments": [
                            str(Path(__file__).with_name("fake_adapter.py")),
                            "0",
                            str(source),
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
                    "--verbose",
                ],
                input="launch fixture.dll\nstop\nquit\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn('"frames":[', result.stdout)
            self.assertIn('"startLine":22', result.stdout)

    def test_variable_reference_error_includes_stop_context(self) -> None:
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
                input="launch fixture.dll\nlocals 10\nvariables 999\nquit\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn('"error":"invalid_variable_reference"', result.stdout)
            self.assertIn('"stopId":1', result.stdout)
            self.assertIn('"stopId":1,"variables":[', result.stdout)
            self.assertIn("Run locals or scopes again", result.stdout)

    def test_variables_can_be_written_without_returning_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory, "fake.json")
            output_path = Path(directory, "exports", "variables.json")
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
                input=(
                    "launch fixture.dll\n"
                    f'variables 10 10 --output "{output_path}"\n'
                    "quit\n"
                ),
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(output_path.is_file())
            exported = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("task", exported["variables"][0]["name"])
            self.assertIn('"outputFile":', result.stdout)
            self.assertIn('"count":1', result.stdout)
            receipt = next(
                line
                for line in result.stdout.splitlines()
                if '"outputFile":' in line
            )
            self.assertNotIn('"variables":', receipt)

    def test_locals_can_be_written_without_returning_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "exports" / "locals.json"
            result = run_cli(
                root,
                write_profile(root),
                (
                    "launch fixture.dll\n"
                    f'locals 10 --output "{output_path}"\n'
                    "quit\n"
                ),
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            exported = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("task", exported["variables"][0]["name"])
            receipt = next(
                line
                for line in result.stdout.splitlines()
                if '"outputFile":' in line
            )
            self.assertIn('"count":1', receipt)
            self.assertNotIn('"variables":', receipt)

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
            self.assertIn('"adapterReaped":true', output)
            self.assertIn('"processTreeClosed":true', output)

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


def write_profile(
    root: Path,
    adapter_id: str = "fake",
    script: str = "fake_adapter.py",
) -> Path:
    """Write a minimal test adapter profile."""
    profile = root / f"{adapter_id}.json"
    profile.write_text(
        json.dumps(
            {
                "id": adapter_id,
                "commandCandidates": [sys.executable],
                "arguments": [str(Path(__file__).with_name(script))],
                "initialize": {"adapterID": adapter_id},
                "launchDefaults": {},
            }
        ),
        encoding="utf-8",
    )
    return profile


def run_cli(
    root: Path,
    profile: Path,
    commands: str,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI against a test profile."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "aidbg.cli",
            "--profile",
            str(profile),
            "--trace-dir",
            str(root / "trace"),
        ],
        input=commands,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


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
