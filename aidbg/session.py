"""Debugger-neutral session operations."""

import asyncio
from pathlib import Path

from aidbg.client import DapClient, DapRequestError
from aidbg.commands import Breakpoint
from aidbg.profile import AdapterProfile
from aidbg.protocol import JsonObject


class DebugSession:
    """Manage one target through one DAP adapter process."""

    def __init__(
        self,
        profile: AdapterProfile,
        client: DapClient,
        trace_directory: Path,
    ) -> None:
        self._profile = profile
        self._client = client
        self._breakpoints: list[Breakpoint] = []
        self._state = "idle"
        self._thread_id: int | None = None
        self.trace_directory = trace_directory

    @classmethod
    async def create(
        cls,
        profile: AdapterProfile,
        trace_directory: Path,
    ) -> "DebugSession":
        """Start and initialize an adapter."""
        client = DapClient(profile, trace_directory)
        try:
            await client.request("initialize", profile.initialize)
            return cls(profile, client, trace_directory)
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
        return await self._wait_execution()

    async def continue_execution(self) -> JsonObject:
        """Continue and wait for the next stop or termination."""
        self._require_stopped()
        self._state = "running"
        await self._client.request(
            "continue",
            {"threadId": self._thread_id},
        )
        return await self._wait_execution()

    async def next(self) -> JsonObject:
        """Step over and wait for the next stop."""
        self._require_stopped()
        self._state = "running"
        await self._client.request("next", {"threadId": self._thread_id})
        return await self._wait_execution()

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

    async def scopes(self) -> list[JsonObject]:
        """Return scopes for the top frame."""
        response = await self._client.request(
            "scopes",
            {"frameId": await self._top_frame_id()},
        )
        return _body_objects(response, "scopes")

    async def variables(
        self,
        reference: int,
        count: int = 50,
    ) -> list[JsonObject]:
        """Return a bounded page of variables."""
        self._require_stopped()
        response = await self._client.request(
            "variables",
            {
                "variablesReference": reference,
                "start": 0,
                "count": count,
            },
        )
        return _body_objects(response, "variables")[:count]

    async def locals(self, count: int = 50) -> list[JsonObject]:
        """Return a bounded page of locals from the top frame."""
        for scope in await self.scopes():
            if (
                isinstance(scope, dict)
                and scope.get("name") == "Locals"
                and isinstance(scope.get("variablesReference"), int)
            ):
                reference = scope["variablesReference"]
                assert isinstance(reference, int)
                return await self.variables(reference, count)
        raise RuntimeError("adapter did not return a Locals scope")

    async def evaluate(self, expression: str) -> JsonObject:
        """Evaluate an expression in the top frame."""
        response = await self._client.request(
            "evaluate",
            {
                "expression": expression,
                "frameId": await self._top_frame_id(),
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
            "breakpoints": [
                f"{item.file}:{item.line}" for item in self._breakpoints
            ],
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

    async def _sync_breakpoints(self, file: Path) -> None:
        breakpoints: list[JsonObject] = []
        for item in self._breakpoints:
            if item.file != file:
                continue
            value: JsonObject = {"line": item.line}
            if item.condition:
                value["condition"] = item.condition
            breakpoints.append(value)
        await self._client.request(
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

    async def _wait_execution(self) -> JsonObject:
        message = await self._client.wait_event(
            {"stopped", "terminated", "exited"},
            timeout=120,
        )
        event = message.get("event")
        body = message.get("body")
        event_body = body if isinstance(body, dict) else {}
        if event == "stopped":
            self._state = "stopped"
            thread_id = event_body.get("threadId")
            self._thread_id = thread_id if isinstance(thread_id, int) else None
            frames = await self.stack(1)
            return {
                "state": self._state,
                "reason": event_body.get("reason"),
                "threadId": self._thread_id,
                "frame": frames[0] if frames else None,
            }
        self._state = "terminated"
        self._thread_id = None
        return {
            "state": self._state,
            "reason": event,
            "exitCode": event_body.get("exitCode"),
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
