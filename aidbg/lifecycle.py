"""Bounded process ownership for debugger adapters and their targets."""

from dataclasses import dataclass
import os
import signal
import subprocess
import threading
from collections.abc import Callable
from typing import cast


@dataclass(frozen=True, slots=True)
class SessionLimits:
    """Upper bounds for debugger operations and cleanup."""

    request_seconds: float = 30
    execution_seconds: float = 120
    shutdown_seconds: float = 3

    def __post_init__(self) -> None:
        for name, value in (
            ("request_seconds", self.request_seconds),
            ("execution_seconds", self.execution_seconds),
            ("shutdown_seconds", self.shutdown_seconds),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")


class ProcessTree:
    """Own an adapter process tree until explicitly closed."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._closed = False
        self._lock = threading.Lock()
        self._windows_job = _WindowsJob(process) if os.name == "nt" else None

    def kill(self, timeout: float) -> None:
        """Kill the complete owned process tree and reap the adapter."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._windows_job is not None:
                self._windows_job.close()
            else:
                try:
                    kill_group = cast(
                        Callable[[int, int], None],
                        getattr(os, "killpg"),
                    )
                    kill_signal = cast(int, getattr(signal, "SIGKILL"))
                    kill_group(self._process.pid, kill_signal)
                except ProcessLookupError:
                    pass
            if self._process.poll() is None:
                self._process.kill()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("adapter process could not be reaped") from error

    @property
    def closed(self) -> bool:
        """Whether ownership was closed and cleanup was attempted."""
        with self._lock:
            return self._closed


def start_owned_process(command: list[str]) -> tuple[subprocess.Popen[bytes], ProcessTree]:
    """Start an isolated adapter process and bind its process-tree owner."""
    if os.name == "nt":
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
    try:
        return process, ProcessTree(process)
    except Exception:
        process.kill()
        process.wait(timeout=3)
        raise


class _WindowsJob:
    """Windows Job Object configured to kill descendants when its handle closes."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            job,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(job)
            raise error
        process_handle = kernel32.OpenProcess(
            0x0100 | 0x0001,
            False,
            process.pid,
        )
        if not process_handle:
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(job)
            raise error
        try:
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                error = ctypes.WinError(ctypes.get_last_error())
                kernel32.CloseHandle(job)
                raise error
        finally:
            kernel32.CloseHandle(process_handle)
        self._handle = job
        self._kernel32 = kernel32

    def close(self) -> None:
        """Close the job, atomically terminating all assigned processes."""
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
