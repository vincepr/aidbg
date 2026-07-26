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


def parse_break_command(value: str) -> Breakpoint:
    """Parse a breakpoint location while preserving its condition verbatim."""
    location, remainder = _split_first_argument(value)
    breakpoint = parse_breakpoint(location)
    if not remainder:
        return breakpoint
    parts = remainder.split(maxsplit=1)
    if (
        len(parts) != 2
        or parts[0].lower() != "if"
        or not parts[1].strip()
    ):
        raise ValueError("usage: break FILE:LINE [if EXPR]")
    return Breakpoint(
        breakpoint.file,
        breakpoint.line,
        parts[1].strip(),
    )


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


def _split_first_argument(value: str) -> tuple[str, str]:
    value = value.lstrip()
    if not value:
        raise ValueError("usage: break FILE:LINE [if EXPR]")
    if value[0] != '"':
        for index, character in enumerate(value):
            if character.isspace():
                return value[:index], value[index:].lstrip()
        return value, ""
    closing_quote = value.find('"', 1)
    if closing_quote < 0:
        raise ValueError("unterminated quoted argument")
    return value[1:closing_quote], value[closing_quote + 1 :].lstrip()
