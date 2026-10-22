from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from mcprobe.cli import main


class CliTests(unittest.TestCase):
    def test_demo_writes_both_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "report.html"
            json_path = Path(temp_dir) / "report.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "doctor",
                        "--demo",
                        "--out",
                        str(html_path),
                        "--json-out",
                        str(json_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("McProbe PASS", stdout.getvalue())
            self.assertNotIn("MCD_MCP_TOKEN=", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
