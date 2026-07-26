from pathlib import Path
import unittest

from aidbg.cli import DEFAULT_SESSION_TIMEOUT_SECONDS
from aidbg.lifecycle import SessionLimits


ROOT = Path(__file__).parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_skill_is_concise_and_contains_runtime_contract(self) -> None:
        skill = (
            ROOT / "skills" / "aidbg-debug" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertLessEqual(len(skill.split()), 250)
        for required in (
            "break FILE:LINE [if EXPR]",
            "wait [--timeout SECONDS]",
            "locals [COUNT] [--frame ID] [--output FILE]",
            "variables REF [COUNT] [--output FILE]",
            "references expire",
            "cleanup receipt",
            "references/setup.md",
        ):
            self.assertIn(required, skill)

    def test_setup_pins_limits_and_parallel_session_isolation(self) -> None:
        setup = (
            ROOT / "skills" / "aidbg-debug" / "references" / "setup.md"
        ).read_text(encoding="utf-8")
        normalized = " ".join(setup.split())

        for required in (
            "30 seconds per DAP request",
            "120 seconds waiting for target execution",
            "3 seconds for cleanup",
            "24-hour hard session lease",
            "Do not share an explicit trace directory between agents",
        ):
            self.assertIn(required, normalized)

    def test_runtime_limit_defaults_match_documented_contract(self) -> None:
        limits = SessionLimits()

        self.assertEqual(30, limits.request_seconds)
        self.assertEqual(120, limits.execution_seconds)
        self.assertEqual(3, limits.shutdown_seconds)
        self.assertEqual(24 * 60 * 60, DEFAULT_SESSION_TIMEOUT_SECONDS)

    def test_runtime_limits_must_be_positive(self) -> None:
        for name in (
            "request_seconds",
            "execution_seconds",
            "shutdown_seconds",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, f"{name} must be positive"):
                    SessionLimits(**{name: 0})

    def test_gitignore_covers_generated_python_and_runtime_state(self) -> None:
        ignored = set(
            (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        )

        self.assertTrue(
            {
                "__pycache__/",
                "*.py[cod]",
                ".aidbg/",
                ".venv/",
                ".mypy_cache/",
                ".pytest_cache/",
                ".ruff_cache/",
                ".coverage",
                "htmlcov/",
            }.issubset(ignored)
        )


if __name__ == "__main__":
    unittest.main()
