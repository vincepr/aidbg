import io
import json
import unittest

from aidbg.protocol import read_message, write_message


class ProtocolTests(unittest.TestCase):
    def test_round_trip_preserves_message(self) -> None:
        stream = io.BytesIO()
        expected: dict[str, object] = {
            "seq": 7,
            "type": "request",
            "command": "threads",
        }

        write_message(stream, expected)
        stream.seek(0)

        self.assertEqual(expected, read_message(stream))

    def test_missing_content_length_is_rejected(self) -> None:
        stream = io.BytesIO(b"Content-Type: application/json\r\n\r\n{}")

        with self.assertRaisesRegex(ValueError, "Content-Length"):
            read_message(stream)

    def test_declared_payload_above_limit_is_rejected_before_body_read(self) -> None:
        stream = io.BytesIO(
            f"Content-Length: {(16 * 1024 * 1024) + 1}\r\n\r\n".encode()
        )

        with self.assertRaisesRegex(ValueError, "exceeds"):
            read_message(stream)

    def test_header_line_above_limit_is_rejected(self) -> None:
        stream = io.BytesIO(b"X" * 8193 + b"\r\n\r\n")

        with self.assertRaisesRegex(ValueError, "header line exceeds"):
            read_message(stream)

    def test_body_length_is_measured_as_utf8_bytes(self) -> None:
        stream = io.BytesIO()

        write_message(stream, {"value": "multibyte-\u00e4"})
        header, body = stream.getvalue().split(b"\r\n\r\n", maxsplit=1)

        self.assertEqual(
            len(body),
            int(header.removeprefix(b"Content-Length: ")),
        )
        self.assertEqual("multibyte-\u00e4", json.loads(body)["value"])


if __name__ == "__main__":
    unittest.main()
