from pathlib import Path
import unittest

from aidbg.commands import (
    Breakpoint,
    parse_break_command,
    parse_breakpoint,
    tokenize,
)


class CommandTests(unittest.TestCase):
    def test_parse_breakpoint_supports_windows_paths(self) -> None:
        actual = parse_breakpoint(r"D:\coding\fixture\TaskResolver.cs:27")

        self.assertEqual(
            Breakpoint(Path(r"D:\coding\fixture\TaskResolver.cs"), 27),
            actual,
        )

    def test_tokenize_preserves_quoted_arguments(self) -> None:
        actual = tokenize(
            'launch "D:\\coding\\fixture with spaces\\app.dll" '
            '--cwd "D:\\coding\\fixture with spaces"'
        )

        self.assertEqual(
            [
                "launch",
                r"D:\coding\fixture with spaces\app.dll",
                "--cwd",
                r"D:\coding\fixture with spaces",
            ],
            actual,
        )

    def test_break_condition_preserves_expression_string_literals(self) -> None:
        actual = parse_break_command(
            '"D:\\coding\\fixture with spaces\\Task.cs:27" '
            'if task.Name == "deploy"'
        )

        self.assertEqual(
            Breakpoint(
                Path(r"D:\coding\fixture with spaces\Task.cs"),
                27,
                'task.Name == "deploy"',
            ),
            actual,
        )

    def test_break_command_accepts_general_whitespace(self) -> None:
        actual = parse_break_command(
            "Fixture.cs:27\tif\ttask.Name == \"deploy\""
        )

        self.assertEqual(
            Breakpoint(
                Path("Fixture.cs"),
                27,
                'task.Name == "deploy"',
            ),
            actual,
        )


if __name__ == "__main__":
    unittest.main()
