"""Debug Adapter Protocol framing."""

from collections.abc import Mapping
import json
from typing import BinaryIO, cast

JsonValue = object
JsonObject = dict[str, object]
MAXIMUM_PAYLOAD_LENGTH = 16 * 1024 * 1024
MAXIMUM_HEADER_LINE_LENGTH = 8 * 1024


def write_message(stream: BinaryIO, message: Mapping[str, JsonValue]) -> None:
    """Write one DAP message and flush the stream."""
    body = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def read_message(stream: BinaryIO) -> JsonObject:
    """Read one DAP message.

    Raises:
        EOFError: If the adapter closes the stream.
        ValueError: If framing or JSON is invalid.
    """
    raw_length: str | None = None
    while True:
        line = stream.readline(MAXIMUM_HEADER_LINE_LENGTH + 1)
        if not line:
            raise EOFError("DAP stream closed while reading headers")
        if len(line) > MAXIMUM_HEADER_LINE_LENGTH:
            raise ValueError("DAP header line exceeds the 8192-byte limit")
        if line == b"\r\n":
            break
        try:
            name, value = line.decode("ascii").split(":", maxsplit=1)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Invalid DAP header") from error
        if name.lower() == "content-length":
            raw_length = value.strip()

    if raw_length is None:
        raise ValueError("DAP header is missing Content-Length")
    try:
        length = int(raw_length)
    except ValueError as error:
        raise ValueError("DAP Content-Length is invalid") from error
    if length < 0:
        raise ValueError("DAP Content-Length is invalid")
    if length > MAXIMUM_PAYLOAD_LENGTH:
        raise ValueError(
            f"DAP Content-Length exceeds the {MAXIMUM_PAYLOAD_LENGTH}-byte limit"
        )

    body = stream.read(length)
    if len(body) != length:
        raise EOFError("DAP stream closed while reading the message body")
    try:
        message = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("DAP body contains invalid JSON") from error
    if not isinstance(message, dict) or not all(
        isinstance(key, str) for key in message
    ):
        raise ValueError("DAP body is not a JSON object")
    return cast(JsonObject, message)
