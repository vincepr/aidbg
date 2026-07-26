"""Debug Adapter Protocol framing."""

from collections.abc import Mapping
import json
from typing import BinaryIO, cast

JsonValue = object
JsonObject = dict[str, object]


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
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise EOFError("DAP stream closed while reading headers")
        if line == b"\r\n":
            break
        try:
            name, value = line.decode("ascii").split(":", maxsplit=1)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Invalid DAP header") from error
        headers[name.lower()] = value.strip()

    raw_length = headers.get("content-length")
    if raw_length is None:
        raise ValueError("DAP header is missing Content-Length")
    try:
        length = int(raw_length)
    except ValueError as error:
        raise ValueError("DAP Content-Length is invalid") from error
    if length < 0:
        raise ValueError("DAP Content-Length is invalid")

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
