import unittest

from aidbg.client import DapRequestError


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


if __name__ == "__main__":
    unittest.main()
