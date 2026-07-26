"""Declarative DAP adapter profiles."""

from dataclasses import dataclass
import glob
import json
import os
from pathlib import Path
import shutil

from aidbg.protocol import JsonObject


@dataclass(frozen=True, slots=True)
class AdapterProfile:
    """Configuration required to start and initialize a DAP adapter."""

    adapter_id: str
    command_candidates: tuple[str, ...]
    arguments: tuple[str, ...]
    initialize: JsonObject
    launch_defaults: JsonObject

    @classmethod
    def load(cls, path: Path) -> "AdapterProfile":
        """Load and validate an adapter profile."""
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("adapter profile must be a JSON object")
        adapter_id = value.get("id")
        candidates = value.get("commandCandidates")
        if not isinstance(adapter_id, str) or not adapter_id:
            raise ValueError("adapter profile requires a non-empty id")
        if not isinstance(candidates, list) or not candidates or not all(
            isinstance(candidate, str) for candidate in candidates
        ):
            raise ValueError("adapter profile requires commandCandidates")
        arguments = value.get("arguments", [])
        initialize = value.get("initialize", {})
        launch_defaults = value.get("launchDefaults", {})
        if not isinstance(arguments, list) or not all(
            isinstance(argument, str) for argument in arguments
        ):
            raise ValueError("adapter profile arguments must be strings")
        if not isinstance(initialize, dict) or not isinstance(launch_defaults, dict):
            raise ValueError("adapter DAP arguments must be JSON objects")
        return cls(
            adapter_id=adapter_id,
            command_candidates=tuple(candidates),
            arguments=tuple(arguments),
            initialize=initialize,
            launch_defaults=launch_defaults,
        )

    def resolve_command(self) -> Path:
        """Resolve the first available adapter command.

        Raises:
            FileNotFoundError: If no configured candidate exists.
        """
        for candidate in self.command_candidates:
            expanded = Path(os.path.expandvars(os.path.expanduser(candidate)))
            matches = sorted(
                (Path(match) for match in glob.glob(str(expanded))),
                reverse=True,
            )
            for match in matches:
                if match.is_file():
                    return match.resolve()
            if expanded.is_absolute() and expanded.is_file():
                return expanded.resolve()
            resolved = shutil.which(str(expanded))
            if resolved is not None:
                return Path(resolved).resolve()
        raise FileNotFoundError(
            f"no executable candidate for adapter {self.adapter_id!r} was found"
        )
