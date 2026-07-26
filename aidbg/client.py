"""Persistent DAP process client."""

import asyncio
from collections.abc import Collection
from concurrent.futures import Future
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
import threading
import time
from typing import BinaryIO, cast

from aidbg.profile import AdapterProfile
from aidbg.protocol import JsonObject, JsonValue, read_message, write_message


class DapRequestError(RuntimeError):
    """A failed DAP request."""

    def __init__(self, command: str, response: JsonObject) -> None:
        self.command = command
        self.response = response
        message = response.get("message")
        if not isinstance(message, str) or not message.strip():
            body = response.get("body")
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("format") if isinstance(error, dict) else None
        if not isinstance(message, str) or not message.strip():
            message = "adapter rejected the request; see DAP trace"
        super().__init__(f"{command}: {message}")


class DapClient:
    """Own one adapter process and correlate its asynchronous messages."""

    def __init__(
        self,
        profile: AdapterProfile,
        trace_directory: Path,
    ) -> None:
        trace_directory.mkdir(parents=True, exist_ok=True)
        self.trace_path = trace_directory / "dap.jsonl"
        self._trace = self.trace_path.open("w", encoding="utf-8")
        self._trace_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, Future[JsonObject]] = {}
        self._pending_lock = threading.Lock()
        self._events: Queue[JsonObject | BaseException] = Queue()
        self._sequence = 0
        self._closed = False
        self._process = subprocess.Popen(
            [str(profile.resolve_command()), *profile.arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        if (
            self._process.stdin is None
            or self._process.stdout is None
            or self._process.stderr is None
        ):
            raise RuntimeError("failed to open adapter standard streams")
        self._reader = threading.Thread(
            target=self._read_messages,
            name="aidbg-dap-reader",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            name="aidbg-dap-stderr",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()

    async def request(
        self,
        command: str,
        arguments: JsonObject | None = None,
        timeout: float = 30,
    ) -> JsonObject:
        """Send one request and return its successful response."""
        response = await self.wait_response(
            self.send_request(command, arguments),
            timeout,
        )
        if response.get("success") is not True:
            raise DapRequestError(command, response)
        return response

    def send_request(
        self,
        command: str,
        arguments: JsonObject | None = None,
    ) -> Future[JsonObject]:
        """Send a request while allowing later protocol work before its response."""
        if self._closed:
            raise RuntimeError("DAP client is closed")
        with self._pending_lock:
            self._sequence += 1
            sequence = self._sequence
            completion: Future[JsonObject] = Future()
            self._pending[sequence] = completion
        message: JsonObject = {
            "seq": sequence,
            "type": "request",
            "command": command,
        }
        if arguments is not None:
            message["arguments"] = arguments
        try:
            self._write("send", message)
        except BaseException:
            with self._pending_lock:
                self._pending.pop(sequence, None)
            raise
        return completion

    async def wait_response(
        self,
        completion: Future[JsonObject],
        timeout: float = 30,
    ) -> JsonObject:
        """Await a response future without blocking the event loop."""
        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(completion),
                timeout,
            )
        except TimeoutError as error:
            raise TimeoutError("timed out waiting for DAP response") from error

    async def wait_event(
        self,
        names: Collection[str],
        timeout: float = 30,
    ) -> JsonObject:
        """Wait for the next event matching one of ``names``."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"timed out waiting for DAP event: {', '.join(names)}"
                )
            try:
                value = await asyncio.to_thread(self._events.get, True, remaining)
            except Empty as error:
                raise TimeoutError(
                    f"timed out waiting for DAP event: {', '.join(names)}"
                ) from error
            if isinstance(value, BaseException):
                raise value
            if value.get("event") in names:
                return value

    @property
    def reaped(self) -> bool:
        """Whether the adapter process has exited."""
        return self._process.poll() is not None

    def close(self) -> None:
        """Terminate the adapter and close the trace."""
        if self._closed:
            return
        self._closed = True
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
        self._reader.join(timeout=2)
        self._stderr_reader.join(timeout=2)
        if self._process.stdout is not None:
            self._process.stdout.close()
        if self._process.stderr is not None:
            self._process.stderr.close()
        self._trace.close()

    def _write(self, direction: str, message: JsonObject) -> None:
        if self._process.stdin is None:
            raise RuntimeError("adapter input is unavailable")
        with self._write_lock:
            self._record(direction, message)
            write_message(cast(BinaryIO, self._process.stdin), message)

    def _read_messages(self) -> None:
        if self._process.stdout is None:
            return
        try:
            while not self._closed:
                message = read_message(cast(BinaryIO, self._process.stdout))
                self._record("recv", message)
                message_type = message.get("type")
                if message_type == "response":
                    request_sequence = message.get("request_seq")
                    if isinstance(request_sequence, int):
                        with self._pending_lock:
                            completion = self._pending.pop(
                                request_sequence,
                                None,
                            )
                        if completion is not None:
                            completion.set_result(message)
                elif message_type == "event":
                    self._events.put(message)
        except BaseException as error:
            if not self._closed:
                self._events.put(error)
                with self._pending_lock:
                    pending = tuple(self._pending.values())
                    self._pending.clear()
                for completion in pending:
                    completion.set_exception(error)

    def _read_stderr(self) -> None:
        if self._process.stderr is None:
            return
        while not self._closed:
            line = self._process.stderr.readline()
            if not line:
                return
            self._record("stderr", line.decode("utf-8", errors="replace").rstrip())

    def _record(self, direction: str, value: JsonValue) -> None:
        record = {
            "at": time.time(),
            "direction": direction,
            "value": value,
        }
        with self._trace_lock:
            self._trace.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            )
            self._trace.write("\n")
            self._trace.flush()
