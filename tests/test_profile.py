import json
import os
from pathlib import Path
import tempfile
import unittest

from aidbg.profile import AdapterProfile


class AdapterProfileTests(unittest.TestCase):
    def test_resolve_command_expands_environment_and_uses_existing_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory, "adapter.exe")
            executable.touch()
            os.environ["AIDBG_TEST_ADAPTER"] = directory
            profile = AdapterProfile(
                adapter_id="test",
                command_candidates=(
                    "%AIDBG_TEST_ADAPTER%/missing.exe",
                    "%AIDBG_TEST_ADAPTER%/adapter.exe",
                ),
                arguments=(),
                initialize={},
                launch_defaults={},
            )

            self.assertEqual(executable.resolve(), profile.resolve_command())

    def test_load_rejects_missing_adapter_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "invalid.json")
            path.write_text(
                json.dumps({"commandCandidates": ["adapter"]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "id"):
                AdapterProfile.load(path)

    def test_resolve_command_supports_versioned_glob_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory, "3.2.0", "netcoredbg", "netcoredbg.exe")
            executable.parent.mkdir(parents=True)
            executable.touch()
            os.environ["AIDBG_TEST_BACKENDS"] = directory
            profile = AdapterProfile(
                adapter_id="test",
                command_candidates=(
                    "%AIDBG_TEST_BACKENDS%/*/netcoredbg/netcoredbg.exe",
                ),
                arguments=(),
                initialize={},
                launch_defaults={},
            )

            self.assertEqual(executable.resolve(), profile.resolve_command())


if __name__ == "__main__":
    unittest.main()
