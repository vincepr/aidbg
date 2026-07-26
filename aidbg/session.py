"""Debugger-neutral session operations."""

import asyncio
from pathlib import Path

from aidbg.client import DapClient, DapRequestError
from aidbg.commands import Breakpoint
from aidbg.lifecycle import SessionLimits
from aidbg.profile import AdapterProfile
from aidbg.protocol import JsonObject


class InvalidVariableReferenceError(RuntimeError):
    """A variable reference rejected by the adapter at the current stop."""

    code = "invalid_variable_reference"


class SessionTerminatedError(RuntimeError):
    """A command tried to reuse a completed adapter session."""

    code = "session_terminated"


class DebugSession:
    """Manage one target through one DAP adapter process."""

    def __init__(
        self,
        profile: AdapterProfile,
        client: DapClient,
        trace_directory: Path,
        limits: SessionLimits,
        verbose: bool,
    ) -> None:
        self._profile = profile
        self._client = client
        self._breakpoints: list[Breakpoint] = []
        self._breakpoint_bindings: dict[Path, list[JsonObject]] = {}
        self._state = "idle"
        self._thread_id: int | None = None
        self._exit_code: int | None = None
        self._target_exited = False
        self._stop_id = 0
        self.trace_directory = trace_directory
        self._limits = limits
        self._verbose = verbose

    @classmethod
    async def create(
        cls,
        profile: AdapterProfile,
        trace_directory: Path,
        limits: SessionLimits | None = None,
        *,
        verbose: bool = False,
    ) -> "DebugSession":
        """Start and initialize an adapter."""
        effective_limits = limits or SessionLimits()
        client = await asyncio.to_thread(
            DapClient,
            profile,
            trace_directory,
            effective_limits,
        )
        try:
            await client.request("initialize", profile.initialize)
            return cls(
                profile,
                client,
                trace_directory,
                effective_limits,
                verbose,
            )
        except Exception:
            client.close()
            raise

    async def add_breakpoint(self, breakpoint: Breakpoint) -> None:
        """Add or replace a source breakpoint."""
        self._breakpoints = [
            item
            for item in self._breakpoints
            if not (
                item.file == breakpoint.file
                and item.line == breakpoint.line
            )
        ]
        self._breakpoints.append(breakpoint)
        if self._state != "idle":
            await self._sync_breakpoints(breakpoint.file)

    async def launch(
        self,
        program: Path,
        cwd: Path,
        arguments: list[str],
    ) -> JsonObject:
        """Launch a target and wait for its first stop or termination."""
        if self._state == "terminated":
            raise SessionTerminatedError(
                "this adapter session has terminated; quit and start a new "
                "aidbg session"
            )
        if self._state != "idle":
            raise RuntimeError("a target is already active")
        launch_arguments = dict(self._profile.launch_defaults)
        launch_arguments.update(
            {
                "program": str(program.resolve()),
                "cwd": str(cwd.resolve()),
                "args": arguments,
            }
        )
        launch_response = self._client.send_request("launch", launch_arguments)
        await self._client.wait_event({"initialized"})
        for file in dict.fromkeys(item.file for item in self._breakpoints):
            await self._sync_breakpoints(file)
        await self._client.request("setExceptionBreakpoints", {"filters": []})
        await self._client.request("configurationDone")
        response = await self._client.wait_response(launch_response)
        if response.get("success") is not True:
            raise DapRequestError("launch", response)
        self._state = "running"
        result = await self._wait_execution()
        bindings = self._all_breakpoint_bindings()
        if bindings:
            result["breakpointBindings"] = bindings
        return result

    async def continue_execution(
        self,
        wait_seconds: float | None = None,
    ) -> JsonObject:
        """Continue and wait for the next stop or termination."""
        self._require_stopped()
        self._state = "running"
        await self._client.request(
            "continue",
            {"threadId": self._thread_id},
        )
        return await self._wait_execution(wait_seconds)

    async def next(self, wait_seconds: float | None = None) -> JsonObject:
        """Step over and wait for the next stop."""
        self._require_stopped()
        self._state = "running"
        await self._client.request("next", {"threadId": self._thread_id})
        return await self._wait_execution(wait_seconds)

    async def wait_for_stop(self, wait_seconds: float | None = None) -> JsonObject:
        """Wait for a running target to stop or terminate."""
        if self._state != "running":
            raise RuntimeError("target is not running")
        return await self._wait_execution(wait_seconds)

    async def stack(self, levels: int = 10) -> list[JsonObject]:
        """Return a bounded call stack."""
        self._require_stopped()
        response = await self._client.request(
            "stackTrace",
            {
                "threadId": self._thread_id,
                "startFrame": 0,
                "levels": levels,
            },
        )
        frames = _body_objects(response, "stackFrames")
        return frames[:levels]

    async def scopes(self, frame_id: int | None = None) -> list[JsonObject]:
        """Return scopes for a frame, defaulting to the top frame."""
        response = await self._client.request(
            "scopes",
            {
                "frameId": (
                    frame_id
                    if frame_id is not None
                    else await self._top_frame_id()
                )
            },
        )
        return _body_objects(response, "scopes")

    async def variables(
        self,
        reference: int,
        count: int = 50,
    ) -> list[JsonObject]:
        """Return a bounded page of variables."""
        self._require_stopped()
        try:
            response = await self._client.request(
                "variables",
                {
                    "variablesReference": reference,
                    "start": 0,
                    "count": count,
                },
            )
        except DapRequestError as error:
            raise InvalidVariableReferenceError(
                f"variable reference {reference} was rejected at stop "
                f"{self._stop_id}; it may belong to an earlier stop. "
                "Run locals or scopes again after every continue or step."
            ) from error
        return _body_objects(response, "variables")[:count]

    async def locals(
        self,
        count: int = 50,
        frame_id: int | None = None,
    ) -> list[JsonObject]:
        """Return a bounded page of locals from a frame."""
        for scope in await self.scopes(frame_id):
            if (
                isinstance(scope, dict)
                and scope.get("name") == "Locals"
                and isinstance(scope.get("variablesReference"), int)
            ):
                reference = scope["variablesReference"]
                assert isinstance(reference, int)
                return await self.variables(reference, count)
        raise RuntimeError("adapter did not return a Locals scope")

    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
    ) -> JsonObject:
        """Evaluate an expression in a frame, defaulting to the top frame."""
        response = await self._client.request(
            "evaluate",
            {
                "expression": expression,
                "frameId": (
                    frame_id
                    if frame_id is not None
                    else await self._top_frame_id()
                ),
                "context": "watch",
            },
        )
        body = response.get("body")
        return body if isinstance(body, dict) else {}

    def status(self) -> JsonObject:
        """Return compact state and trace location."""
        return {
            "state": self._state,
            "threadId": self._thread_id,
            "stopId": self._stop_id,
            "exitCode": self._exit_code,
            "breakpoints": [
                f"{item.file}:{item.line}" for item in self._breakpoints
            ],
            "breakpointBindings": self._all_breakpoint_bindings(),
            "traceDirectory": str(self.trace_directory),
        }

    async def stop(self) -> None:
        """Disconnect and terminate the target."""
        if self._state in {"idle", "terminated"}:
            return
        try:
            await self._client.request(
                "disconnect",
                {"restart": False, "terminateDebuggee": True},
            )
        finally:
            self._state = "terminated"
            self._thread_id = None

    async def close(self) -> None:
        """Release the adapter process."""
        if self._state not in {"idle", "terminated"}:
            try:
                await self.stop()
            except Exception:
                pass
        await asyncio.to_thread(self._client.close)

    def force_close(self) -> None:
        """Synchronously kill the adapter tree for hard lease enforcement."""
        self._state = "terminated"
        self._thread_id = None
        self._client.close()

    def cleanup_receipt(self) -> JsonObject:
        """Return authoritative process cleanup state."""
        return {
            **self.status(),
            "targetExited": (
                self._target_exited or self._client.process_tree_closed
            ),
            "adapterReaped": self._client.reaped,
            "processTreeClosed": self._client.process_tree_closed,
        }

    @property
    def adapter_reaped(self) -> bool:
        """Whether the owned adapter process has exited."""
        return self._client.reaped

    @property
    def stop_id(self) -> int:
        """Return the current stop generation."""
        return self._stop_id

    async def _sync_breakpoints(self, file: Path) -> None:
        breakpoints: list[JsonObject] = []
        for item in self._breakpoints:
            if item.file != file:
                continue
            value: JsonObject = {"line": item.line}
            if item.condition:
                value["condition"] = item.condition
            breakpoints.append(value)
        response = await self._client.request(
            "setBreakpoints",
            {
                "source": {
                    "name": file.name,
                    "path": str(file.resolve()),
                },
                "breakpoints": breakpoints,
                "sourceModified": False,
            },
        )
        adapter_breakpoints = _body_objects(response, "breakpoints")
        bindings: list[JsonObject] = []
        for index, requested in enumerate(
            item for item in self._breakpoints if item.file == file
        ):
            adapter = (
                adapter_breakpoints[index]
                if index < len(adapter_breakpoints)
                else {}
            )
            resolved_line = adapter.get("line")
            binding: JsonObject = {
                "path": str(file.resolve()),
                "line": (
                    resolved_line
                    if isinstance(resolved_line, int)
                    else requested.line
                ),
                "verified": adapter.get("verified"),
            }
            message = adapter.get("message")
            if isinstance(message, str):
                binding["message"] = message
            if requested.condition:
                binding["condition"] = requested.condition
            breakpoint_id = adapter.get("id")
            if isinstance(breakpoint_id, int):
                binding["id"] = breakpoint_id
            bindings.append(binding)
        self._breakpoint_bindings[file] = bindings

    def _all_breakpoint_bindings(self) -> list[JsonObject]:
        return [
            binding
            for file_bindings in self._breakpoint_bindings.values()
            for binding in file_bindings
        ]

    async def _wait_execution(
        self,
        wait_seconds: float | None = None,
    ) -> JsonObject:
        try:
            message = await self._client.wait_event(
                {"stopped", "terminated", "exited"},
                timeout=wait_seconds or self._limits.execution_seconds,
            )
        except TimeoutError:
            return {
                "state": "running",
                "waitTimedOut": True,
                "hint": "Use wait --timeout SECONDS or stop.",
            }
        event = message.get("event")
        body = message.get("body")
        event_body = body if isinstance(body, dict) else {}
        if event == "stopped":
            self._state = "stopped"
            self._stop_id += 1
            thread_id = event_body.get("threadId")
            self._thread_id = thread_id if isinstance(thread_id, int) else None
            frames = await self.stack(10 if self._verbose else 1)
            frame = frames[0] if frames else None
            source_context = _source_context(
                frame,
                radius=5 if self._verbose else 1,
            )
            snapshot: JsonObject = {
                "state": self._state,
                "reason": event_body.get("reason"),
                "threadId": self._thread_id,
                "stopId": self._stop_id,
                "frame": frame,
            }
            if source_context is not None:
                snapshot["sourceContext"] = source_context
            if self._verbose:
                snapshot["frames"] = frames
            return snapshot
        self._state = "terminated"
        self._thread_id = None
        self._target_exited = True
        exit_code = event_body.get("exitCode")
        if isinstance(exit_code, int):
            self._exit_code = exit_code
        return {
            "state": self._state,
            "reason": event,
            "exitCode": self._exit_code,
        }

    async def _top_frame_id(self) -> int:
        frames = await self.stack(1)
        if not frames or not isinstance(frames[0], dict):
            raise RuntimeError("adapter returned no stack frame")
        frame_id = frames[0].get("id")
        if not isinstance(frame_id, int):
            raise RuntimeError("adapter returned a frame without an integer id")
        return frame_id

    def _require_stopped(self) -> None:
        if self._state != "stopped" or self._thread_id is None:
            raise RuntimeError("target is not stopped")


def _body_objects(response: JsonObject, name: str) -> list[JsonObject]:
    body = response.get("body")
    if not isinstance(body, dict):
        return []
    value = body.get(name)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _source_context(
    frame: JsonObject | None,
    radius: int,
) -> JsonObject | None:
    if frame is None:
        return None
    source = frame.get("source")
    line = frame.get("line")
    path = source.get("path") if isinstance(source, dict) else None
    if not isinstance(path, str) or not isinstance(line, int) or line < 1:
        return None
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return {
        "startLine": start,
        "lines": lines[start - 1 : end],
    }
