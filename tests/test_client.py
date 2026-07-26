from concurrent.futures import Future
import unittest

from aidbg.client import DapClient, DapRequestError
from aidbg.lifecycle import SessionLimits
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


if __name__ == "__main__":
    unittest.main()
