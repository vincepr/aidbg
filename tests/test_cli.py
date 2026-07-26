import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliTests(unittest.TestCase):
    def test_quit_exits_successfully_without_false_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory, "fake.json")
            profile.write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "commandCandidates": [sys.executable],
                        "arguments": [
                            str(Path(__file__).with_name("fake_adapter.py"))
                        ],
                        "initialize": {"adapterID": "fake"},
                        "launchDefaults": {},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aidbg.cli",
                    "--profile",
                    str(profile),
                    "--trace-dir",
                    str(Path(directory, "trace")),
                ],
                input="quit\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn('"ok":false', result.stdout)


if __name__ == "__main__":
    unittest.main()
