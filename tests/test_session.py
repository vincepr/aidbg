import asyncio
from pathlib import Path
import sys
import tempfile
import time
from typing import cast
import unittest

from aidbg.commands import Breakpoint
from aidbg.lifecycle import SessionLimits
from aidbg.profile import AdapterProfile
from aidbg.session import (
    DebugSession,
    InvalidVariableReferenceError,
    SessionTerminatedError,
)


class DebugSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_surfaces_unverified_breakpoint_binding(self) -> None:
        profile = AdapterProfile(
            adapter_id="fake",
            command_candidates=(sys.executable,),
            arguments=(
                str(Path(__file__).with_name("fake_adapter.py")),
                "0",
                "Fixture.cs",
                "pending",
            ),
            initialize={"adapterID": "fake"},
            launch_defaults={},
        )
        with tempfile.TemporaryDirectory() as directory:
            session = await DebugSession.create(profile, Path(directory))
            try:
                await session.add_breakpoint(
                    Breakpoint(Path("Fixture.cs"), 27, 'task.Name == "deploy"')
                )

                stopped = await session.launch(
                    Path("fixture.dll"),
                    Path.cwd(),
                    [],
                )

                self.assertEqual(
                    [
                        {
                            "path": str(Path("Fixture.cs").resolve()),
                            "line": 27,
                            "verified": False,
                            "message": "pending test binding",
                            "condition": 'task.Name == "deploy"',
                        }
                    ],
                    stopped["breakpointBindings"],
                )
            finally:
                await session.close()

    async def test_stop_snapshot_has_generation_and_bounded_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "Fixture.cs")
            source.write_text(
                "".join(f"line {line}\n" for line in range(1, 31)),
                encoding="utf-8",
            )
            profile = AdapterProfile(
                adapter_id="fake",
                command_candidates=(sys.executable,),
                arguments=(
                    str(Path(__file__).with_name("fake_adapter.py")),
                    "0",
                    str(source),
                ),
                initialize={"adapterID": "fake"},
                launch_defaults={},
            )
            session = await DebugSession.create(profile, Path(directory, "trace"))
            try:
                stopped = await session.launch(
                    Path("fixture.dll"),
                    Path.cwd(),
                    [],
                )

                self.assertEqual(1, stopped["stopId"])
                self.assertEqual(
                    {
                        "startLine": 26,
                        "lines": ["line 26", "line 27", "line 28"],
                    },
                    stopped["sourceContext"],
                )
                self.assertNotIn("frames", stopped)
            finally:
                await session.close()

    async def test_verbose_stop_snapshot_adds_bounded_stack_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "Fixture.cs")
            source.write_text(
                "".join(f"line {line}\n" for line in range(1, 31)),
                encoding="utf-8",
            )
            profile = AdapterProfile(
                adapter_id="fake",
                command_candidates=(sys.executable,),
                arguments=(
                    str(Path(__file__).with_name("fake_adapter.py")),
                    "0",
                    str(source),
                ),
                initialize={"adapterID": "fake"},
                launch_defaults={},
            )
            session = await DebugSession.create(
                profile,
                Path(directory, "trace"),
                verbose=True,
            )
            try:
                stopped = await session.launch(
                    Path("fixture.dll"),
                    Path.cwd(),
                    [],
                )

                frames = cast(list[object], stopped["frames"])
                self.assertEqual(1, len(frames))
                context = cast(dict[str, object], stopped["sourceContext"])
                lines = cast(list[object], context["lines"])
                self.assertEqual(22, context["startLine"])
                self.assertEqual(9, len(lines))
            finally:
                await session.close()

    async def test_launch_inspect_and_continue_to_termination(self) -> None:
        profile = AdapterProfile(
            adapter_id="fake",
            command_candidates=(sys.executable,),
            arguments=(str(Path(__file__).with_name("fake_adapter.py")),),
            initialize={"adapterID": "fake"},
            launch_defaults={},
        )
        with tempfile.TemporaryDirectory() as directory:
            session = await DebugSession.create(profile, Path(directory))
            try:
                await session.add_breakpoint(Breakpoint(Path("Fixture.cs"), 27))

                stopped = await session.launch(Path("fixture.dll"), Path.cwd(), [])
                locals_ = await session.locals(20)
                evaluation = await session.evaluate("task.Name", frame_id=321)
                terminated = await session.continue_execution()

                self.assertEqual("stopped", stopped["state"])
                self.assertNotIn("sourceContext", stopped)
                self.assertEqual("docs", locals_[0]["value"])
                self.assertEqual("docs", evaluation["result"])
                self.assertEqual(321, evaluation["frameId"])
                self.assertEqual("terminated", terminated["state"])
                self.assertTrue(Path(directory, "dap.jsonl").is_file())
            finally:
                await session.close()

    async def test_terminated_session_rejects_relaunch_with_recovery(self) -> None:
        profile = AdapterProfile(
            adapter_id="fake",
            command_candidates=(sys.executable,),
            arguments=(str(Path(__file__).with_name("fake_adapter.py")),),
            initialize={"adapterID": "fake"},
            launch_defaults={},
        )
        with tempfile.TemporaryDirectory() as directory:
            session = await DebugSession.create(profile, Path(directory))
            try:
                await session.launch(Path("fixture.dll"), Path.cwd(), [])
                await session.continue_execution()

                with self.assertRaises(SessionTerminatedError) as raised:
                    await session.launch(Path("fixture.dll"), Path.cwd(), [])

                self.assertEqual("session_terminated", raised.exception.code)
                self.assertIn("start a new aidbg session", str(raised.exception))
            finally:
                await session.close()

    async def test_invalid_variable_reference_has_stop_scoped_guidance(self) -> None:
        profile = AdapterProfile(
            adapter_id="fake",
            command_candidates=(sys.executable,),
            arguments=(str(Path(__file__).with_name("fake_adapter.py")),),
            initialize={"adapterID": "fake"},
            launch_defaults={},
        )
        with tempfile.TemporaryDirectory() as directory:
            session = await DebugSession.create(profile, Path(directory))
            try:
                stopped = await session.launch(
                    Path("fixture.dll"),
                    Path.cwd(),
                    [],
                )

                with self.assertRaisesRegex(
                    InvalidVariableReferenceError,
                    "stop 1.*Run locals or scopes again",
                ):
                    await session.variables(999)

                self.assertEqual(stopped["stopId"], session.status()["stopId"])
            finally:
                await session.close()

    async def test_parallel_sessions_keep_state_and_traces_isolated(self) -> None:
        profile = AdapterProfile(
            adapter_id="fake",
            command_candidates=(sys.executable,),
            arguments=(str(Path(__file__).with_name("fake_adapter.py")),),
            initialize={"adapterID": "fake"},
            launch_defaults={},
        )

        async def run_one(directory: Path, line: int) -> tuple[str, str]:
            session = await DebugSession.create(profile, directory)
            try:
                await session.add_breakpoint(Breakpoint(Path("Fixture.cs"), line))
                stopped = await session.launch(
                    Path(f"fixture-{line}.dll"),
                    Path.cwd(),
                    [],
                )
                await session.continue_execution()
                return (
                    str(stopped["state"]),
                    str(session.status()["breakpoints"]),
                )
            finally:
                await session.close()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = await asyncio.gather(
                *(run_one(root / f"session-{index}", 20 + index) for index in range(4))
            )

            self.assertEqual(["stopped"] * 4, [result[0] for result in results])
            for index, (_, breakpoints) in enumerate(results):
                self.assertIn(f":{20 + index}", breakpoints)
                self.assertTrue((root / f"session-{index}" / "dap.jsonl").is_file())

    async def test_unresponsive_adapter_operation_is_bounded_and_reaped(self) -> None:
        profile = AdapterProfile(
            adapter_id="hanging",
            command_candidates=(sys.executable,),
            arguments=(str(Path(__file__).with_name("hanging_adapter.py")),),
            initialize={"adapterID": "hanging"},
            launch_defaults={},
        )
        limits = SessionLimits(
            request_seconds=1.5,
            execution_seconds=0.2,
            shutdown_seconds=0.5,
        )
        with tempfile.TemporaryDirectory() as directory:
            session = await DebugSession.create(profile, Path(directory), limits)
            started = time.monotonic()
            try:
                with self.assertRaises(TimeoutError):
                    await session.launch(Path("fixture.dll"), Path.cwd(), [])
            finally:
                await session.close()

            self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(session.adapter_reaped)

    async def test_execution_wait_timeout_is_nonfatal(self) -> None:
        profile = AdapterProfile(
            adapter_id="fake",
            command_candidates=(sys.executable,),
            arguments=(
                str(Path(__file__).with_name("fake_adapter.py")),
                "0.2",
            ),
            initialize={"adapterID": "fake"},
            launch_defaults={},
        )
        limits = SessionLimits(
            request_seconds=1,
            execution_seconds=0.05,
            shutdown_seconds=0.5,
        )
        with tempfile.TemporaryDirectory() as directory:
            session = await DebugSession.create(profile, Path(directory), limits)
            try:
                await session.add_breakpoint(Breakpoint(Path("Fixture.cs"), 27))
                await session.launch(Path("fixture.dll"), Path.cwd(), [])

                timed_out = await session.continue_execution()
                terminated = await session.wait_for_stop(0.5)

                self.assertEqual("running", timed_out["state"])
                self.assertTrue(timed_out["waitTimedOut"])
                self.assertIn("wait", cast(str, timed_out["hint"]))
                self.assertEqual("terminated", terminated["state"])
            finally:
                await session.close()


if __name__ == "__main__":
    unittest.main()
