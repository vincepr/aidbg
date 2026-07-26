import asyncio
from concurrent.futures import Future
from pathlib import Path
import sys
import tempfile
import time
import unittest

from aidbg.client import AdapterExitedError, DapClient, DapRequestError
from aidbg.lifecycle import SessionLimits
from aidbg.profile import AdapterProfile
from aidbg.protocol import JsonObject


class DapRequestErrorTests(unittest.TestCase):
    def test_empty_adapter_error_points_to_trace(self) -> None:
        error = DapRequestError(
            "evaluate",
            {"type": "response", "success": False, "message": ""},
        )

        self.assertEqual(
            "evaluate: adapter rejected the request; see DAP trace",
            str(error),
        )


class DapResponseTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_does_not_cancel_late_adapter_response(self) -> None:
        client = object.__new__(DapClient)
        client._limits = SessionLimits()
        completion: Future[JsonObject] = Future()

        with self.assertRaisesRegex(TimeoutError, "DAP response"):
            await client.wait_response(completion, timeout=0.01)

        self.assertFalse(completion.cancelled())
        completion.set_result({"type": "response", "success": True})
        response = await client.wait_response(completion, timeout=0.1)
        self.assertTrue(response["success"])

    async def test_dead_adapter_has_stable_error_with_diagnostics(self) -> None:
        profile = AdapterProfile(
            adapter_id="exiting",
            command_candidates=(sys.executable,),
            arguments=(str(Path(__file__).with_name("exiting_adapter.py")),),
            initialize={"adapterID": "exiting"},
            launch_defaults={},
        )
        with tempfile.TemporaryDirectory() as directory:
            trace_directory = Path(directory)
            client = DapClient(profile, trace_directory, SessionLimits())
            try:
                await client.request("initialize", profile.initialize)
                with self.assertRaises(DapRequestError):
                    await client.request("evaluate")

                deadline = time.monotonic() + 2
                while not client.reaped and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)

                with self.assertRaises(AdapterExitedError) as raised:
                    await client.request("stackTrace")

                self.assertEqual("adapter_exited", raised.exception.code)
                self.assertEqual(23, raised.exception.exit_code)
                self.assertEqual(
                    trace_directory / "dap.jsonl",
                    raised.exception.trace_path,
                )
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
