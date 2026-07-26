import asyncio
from pathlib import Path
import sys
import tempfile
import time
import unittest

from aidbg.commands import Breakpoint
from aidbg.lifecycle import SessionLimits
from aidbg.profile import AdapterProfile
from aidbg.session import DebugSession


class DebugSessionTests(unittest.IsolatedAsyncioTestCase):
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
                self.assertEqual("docs", locals_[0]["value"])
                self.assertEqual("docs", evaluation["result"])
                self.assertEqual(321, evaluation["frameId"])
                self.assertEqual("terminated", terminated["state"])
                self.assertTrue(Path(directory, "dap.jsonl").is_file())
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


if __name__ == "__main__":
    unittest.main()
