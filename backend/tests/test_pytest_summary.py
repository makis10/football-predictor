"""The CI job summary for the backend suite.

Worth testing because of when it runs: the interesting branch is the one that
only executes on a red build, which is the moment nobody wants to also be
debugging the reporter. The green path is checked on every push by simply
existing; the failure path is checked here.
"""
from __future__ import annotations

from scripts.pytest_summary import render

_GREEN = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="1"
                       tests="3" time="12.5">
  <testcase classname="backend.tests.test_tickets" name="test_a" time="0.1"/>
  <testcase classname="backend.tests.test_tickets" name="test_b" time="0.1"/>
  <testcase classname="backend.tests.test_odds" name="test_c" time="0.1">
    <skipped message="no key"/>
  </testcase>
</testsuite></testsuites>"""

_RED = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="1" skipped="0"
                       tests="3" time="4.0">
  <testcase classname="backend.tests.test_tickets" name="test_ok" time="0.1"/>
  <testcase classname="backend.tests.test_tickets" name="test_dup" time="0.1">
    <failure message="AssertionError: safe carries the same match twice"/>
  </testcase>
  <testcase classname="backend.tests.test_odds" name="test_boom" time="0.1">
    <error message="ConnectionError: refused"/>
  </testcase>
</testsuite></testsuites>"""


def _write(tmp_path, body):
    p = tmp_path / "report.xml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_a_green_run_reports_every_test_it_ran(tmp_path):
    out = render(_write(tmp_path, _GREEN))

    assert "✅ 2 passes" in out
    assert "⏭️ 1 skipped" in out
    assert "3 total" in out
    assert "✅ 2 passed · 2 total" in out, "test-file count is wrong"
    assert "### Failures" not in out


def test_a_red_run_names_what_failed(tmp_path):
    """The count alone sends you to the raw log, which is what this replaces."""
    out = render(_write(tmp_path, _RED))

    assert "test_dup" in out and "same match twice" in out
    assert "test_boom" in out and "ConnectionError" in out
    assert "❌ 1 failures" in out and "💥 1 errors" in out


def test_passes_are_never_marked_as_a_failure(tmp_path):
    """'❌ 1 passes' read as though the passing tests had failed."""
    out = render(_write(tmp_path, _RED))

    assert "✅ 1 passes" in out
    assert "❌ 1 passes" not in out


def test_a_file_with_one_bad_test_counts_as_one_failed_file(tmp_path):
    out = render(_write(tmp_path, _RED))

    assert "❌ 2 failed · ✅ 0 passed · 2 total" in out


def test_a_missing_report_says_so_instead_of_raising(tmp_path):
    """The reporter runs with `if: always()`, so it meets runs that died before
    writing anything. Crashing there would bury the real error."""
    out = render(str(tmp_path / "never-written.xml"))

    assert "No report to read" in out
    assert "FileNotFoundError" in out


def test_a_truncated_report_says_so_instead_of_raising(tmp_path):
    out = render(_write(tmp_path, "<testsuites><testsuite tests="))

    assert "No report to read" in out


def test_the_older_bare_testsuite_root_is_still_read(tmp_path):
    """pytest used to write <testsuite> at the root with no <testsuites> wrapper."""
    bare = _GREEN.replace("<testsuites>", "").replace("</testsuites>", "")

    assert "✅ 2 passes" in render(_write(tmp_path, bare))
