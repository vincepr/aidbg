"""Parsing for the compact aidbg command language."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Breakpoint:
    """A source-line breakpoint."""

    file: Path
    line: int
    condition: str | None = None


def parse_breakpoint(value: str) -> Breakpoint:
    """Parse ``file:line``, including Windows drive-letter paths."""
    file, separator, raw_line = value.rpartition(":")
    if not separator:
        raise ValueError("expected breakpoint as file:line")
    try:
        line = int(raw_line)
    except ValueError as error:
        raise ValueError("breakpoint line must be an integer") from error
    if not file or line < 1:
        raise ValueError("expected breakpoint as file:line")
    return Breakpoint(Path(file), line)


def tokenize(value: str) -> list[str]:
    """Split a command while preserving quoted paths and backslashes."""
    result: list[str] = []
    current: list[str] = []
    quoted = False
    for character in value:
        if character == '"':
            quoted = not quoted
        elif character.isspace() and not quoted:
            if current:
                result.append("".join(current))
                current.clear()
        else:
            current.append(character)
    if quoted:
        raise ValueError("unterminated quoted argument")
    if current:
        result.append("".join(current))
    return result
