#!/usr/bin/env python3
"""Render a pytest JUnit XML report as the GitHub Actions job summary.

Why this exists: the CI page showed "66 tests" and nothing else, because vitest
writes a job summary of its own accord and pytest does not. The backend job was
green the whole time — its 418 tests were simply buried in the step log, which
made the frontend's 66 look like the project's entire suite.

No plugin: pytest emits JUnit XML natively with --junitxml, and this parses it
with the standard library. Written to $GITHUB_STEP_SUMMARY when that is set,
stdout otherwise, so it is runnable locally:

    python -m pytest backend/tests/ -q --junitxml=report.xml
    python scripts/pytest_summary.py report.xml
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET


def _suites(root: ET.Element) -> list[ET.Element]:
    """pytest writes <testsuites><testsuite>…; older versions wrote the
    <testsuite> alone at the root."""
    return [root] if root.tag == "testsuite" else list(root.iter("testsuite"))


def render(xml_path: str) -> str:
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        # A missing or truncated report must not fail the job on top of
        # whatever already went wrong — say so and let the step log stand.
        return f"## Pytest Test Report\n\n_No report to read: {type(exc).__name__}._\n"

    cases: list[ET.Element] = []
    total = failures = errors = skipped = 0
    seconds = 0.0
    for suite in _suites(root):
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        seconds += float(suite.get("time", 0) or 0)
        cases.extend(suite.iter("testcase"))

    passed = total - failures - errors - skipped
    files = {c.get("classname", "").split(".")[-1] for c in cases if c.get("classname")}

    bad = [c for c in cases
           if c.find("failure") is not None or c.find("error") is not None]
    bad_files = {c.get("classname", "").split(".")[-1] for c in bad}

    out = ["## Pytest Test Report", "", "### Summary", ""]
    if bad_files:
        out.append(f"- Test Files: ❌ {len(bad_files)} failed · "
                   f"✅ {len(files) - len(bad_files)} passed · {len(files)} total")
    else:
        out.append(f"- Test Files: ✅ {len(files)} passed · {len(files)} total")
    # The pass count always gets a tick: it says how many passed, it is not a
    # verdict on the run. Marking it ❌ because something else failed rendered
    # as "❌ 1 passes", which reads as the passes themselves having failed.
    parts = [f"✅ {passed} passes"]
    if failures:
        parts.append(f"❌ {failures} failures")
    if errors:
        parts.append(f"💥 {errors} errors")
    if skipped:
        parts.append(f"⏭️ {skipped} skipped")
    out.append(f"- Test Results: {' · '.join(parts)} · {total} total")
    out.append(f"- Duration: {seconds:.1f}s")

    if bad:
        out += ["", "### Failures", ""]
        for c in bad[:40]:          # a wall of 300 tracebacks helps nobody
            node = c.find("failure")
            if node is None:
                node = c.find("error")
            first = (node.get("message") or "").strip().splitlines()
            out.append(f"- `{c.get('classname')}::{c.get('name')}` — "
                       f"{first[0] if first else 'failed'}")
        if len(bad) > 40:
            out.append(f"- …and {len(bad) - 40} more; see the step log.")
    return "\n".join(out) + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    text = render(sys.argv[1])
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
