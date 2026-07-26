import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from aidbg.commands import Breakpoint
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


if __name__ == "__main__":
    unittest.main()
