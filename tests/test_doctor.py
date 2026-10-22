from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcprobe.baseline import EXPECTED_TOOL_COUNT
from mcprobe.doctor import run_fixture, run_live
from mcprobe.fixtures import healthy_fixture, missing_tool_fixture
from mcprobe.report import render_html, write_html


class DoctorFixtureTests(unittest.TestCase):
    def test_healthy_fixture_passes(self) -> None:
        result = run_fixture(healthy_fixture())

        self.assertEqual(result["overall_status"], "pass")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["contract"]["actual_count"], EXPECTED_TOOL_COUNT)
        self.assertEqual(result["contract"]["missing"], [])
        self.assertEqual(result["contract"]["unexpected"], [])
        self.assertEqual(result["privacy"]["writes_executed"], 0)

    def test_missing_tool_is_a_failure(self) -> None:
        result = run_fixture(missing_tool_fixture())

        self.assertEqual(result["overall_status"], "fail")
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("now-time-info", result["contract"]["missing"])
        self.assertIn("experimental-tool", result["contract"]["unexpected"])

    def test_account_probe_is_redacted(self) -> None:
        result = run_fixture(healthy_fixture(), account=True)
        account = next(
            probe for probe in result["probes"] if probe["name"] == "query-my-account"
        )

        self.assertEqual(account["status"], "pass")
        self.assertEqual(account["text_preview"], "内容已隐藏（隐私模式）")
        self.assertFalse(result["privacy"]["raw_account_content_in_report"])

    def test_report_is_self_contained_and_escapes_content(self) -> None:
        fixture = healthy_fixture()
        fixture["label"] = "<script>alert(1)</script>"
        result = run_fixture(fixture)
        document = render_html(result)

        self.assertTrue(document.startswith("<!doctype html>"))
        self.assertNotIn("<script>alert(1)</script>", document)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", document)
        self.assertIn("McProbe", document)

    def test_write_tools_are_presence_only(self) -> None:
        result = run_fixture(healthy_fixture())
        write_tools = [tool for tool in result["tools"] if tool["risk"] == "write"]

        self.assertGreater(len(write_tools), 0)
        self.assertEqual(result["privacy"]["writes_executed"], 0)

    def test_html_can_be_written_to_nested_path(self) -> None:
        result = run_fixture(healthy_fixture())
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "report.html"
            write_html(result, output)

            self.assertTrue(output.exists())
            self.assertIn("麦门接口", output.read_text(encoding="utf-8"))

    def test_missing_live_token_fails_without_network(self) -> None:
        result = run_live(token="", endpoint="https://invalid.example")

        self.assertEqual(result["overall_status"], "fail")
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(result["source"]["token_configured"])
        self.assertEqual(result["privacy"]["writes_executed"], 0)


if __name__ == "__main__":
    unittest.main()
