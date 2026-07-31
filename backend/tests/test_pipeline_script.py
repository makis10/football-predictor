"""Structural invariants of the scheduled shell pipeline.

run_daily.sh is 700 lines of bash that nothing type-checks and no unit test
exercises, yet it is the only thing that keeps the site's data fresh. Every
assertion below is a bug that reached production and was found by reading logs
after the fact.

These parse the script as text rather than running it — fast, offline, and they
fail on the pull request instead of at 06:00 three weeks later.
"""
from __future__ import annotations

import os
import re

import pytest

_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")


def _read(name: str) -> str:
    with open(os.path.join(_SCRIPTS, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def daily() -> str:
    return _read("run_daily.sh")


def _code_only(script: str) -> str:
    """Strip comments and blank lines.

    The header of run_daily.sh documents the pipeline in prose and mentions
    "docker compose exec" three paragraphs before any command runs — matching
    that would make the ordering check assert on a sentence.
    """
    out = []
    for line in script.splitlines():
        stripped = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
        if stripped.strip():
            out.append(stripped)
    return "\n".join(out)


# ── Ordering ──────────────────────────────────────────────────────────────────

def test_docker_is_awaited_before_any_container_command(daily):
    """`wait_for_docker` must precede the first `docker compose exec`.

    2026-07-31: the API-Football pre-flight sat ABOVE the guard. launchd fires
    this job on wake, when Docker Desktop is often still starting, so the
    pre-flight got "failed to connect to the docker API", exited 1, and set
    API_FOOTBALL_OK=0 — disabling every API-Football step for the whole run —
    while the very next line waited for the daemon and found it ready.
    """
    code = _code_only(daily)
    wait_at = code.index("wait_for_docker \"$LOG\"")
    first_exec = code.index("docker compose exec")
    assert wait_at < first_exec, (
        "a container command runs before wait_for_docker; on a cold start it "
        "will fail and may disable later steps")


# ── Failure accounting ────────────────────────────────────────────────────────

def test_every_step_failure_records_which_step(daily):
    """Steps must fail via `_fail $LINENO`, never a bare flag.

    A bare `overall_failed=1` reports "one or more steps failed" with no way to
    tell which one without re-reading thousands of log lines — which is exactly
    how a two-week failure streak went undiagnosed.
    """
    # The one legitimate assignment lives inside the _fail() helper itself.
    body = re.sub(r"_fail\(\)\s*\{.*?\n\}", "", _code_only(daily), flags=re.S)
    bare = re.findall(r"^\s*overall_failed=1\s*$", body, re.MULTILINE)
    assert not bare, (
        f"{len(bare)} bare `overall_failed=1` assignment(s) — use `_fail $LINENO` "
        "so the run summary can name the step")


def test_data_completeness_does_not_gate_the_heartbeat(daily):
    """Data-quality alerts must not masquerade as "the pipeline didn't run".

    The health check exits 1 on ANY alert. While that fed `overall_failed` the
    dead-man's-switch ping was skipped on almost every run — 0 heartbeats ever
    sent — so healthchecks.io would have shown "down" forever while the pipeline
    completed happily, and would never have flagged a run that truly never
    happened.
    """
    health = re.search(r"check_data_completeness\.py[^\n]*\n[^\n]*", daily)
    assert health, "health check step not found"
    assert "_fail" not in health.group(0), (
        "the data-completeness check feeds overall_failed again — it must set "
        "its own health_alerts flag so the heartbeat stays independent")
    assert "health_alerts=1" in health.group(0)


def test_heartbeat_is_sent_only_when_no_step_failed(daily):
    """The ping is the dead-man's switch; it must reflect execution, nothing else."""
    assert re.search(r'if \[ "\$overall_failed" -ne 0 \]', daily), \
        "heartbeat branch no longer keys off overall_failed"
    assert "HEARTBEAT_URL" in daily


# ── Alerting ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("script", ["run_daily.sh", "run_watchdog.sh"])
def test_every_alert_tells_the_reader_which_log_to_open(script):
    """`send_alert` must be passed a log file.

    An alert that says what broke but not where to read about it sends you
    hunting through ~/Library/Logs at the worst possible moment.
    """
    body = _read(script)
    # Each call spans continuation lines up to the first line not ending in "\".
    calls = re.findall(r"send_alert\b(?:[^\n]*\\\n)*[^\n]*", body)
    assert calls, f"{script}: no send_alert calls found — did the helper move?"
    for call in calls:
        args = call.split()
        # title, message, priority, tags, logfile → the 5th argument must exist.
        assert len(args) >= 5 or ".log" in call, (
            f"{script}: send_alert without a log argument:\n{call.strip()}")


def test_alert_helper_puts_the_path_where_it_can_be_seen():
    """macOS notifications truncate; the path belongs in the subtitle."""
    alert = _read("_alert.sh")
    assert "subtitle" in alert, "log path is no longer surfaced on the macOS notification"
    assert "tail -" in alert, "phone push no longer carries a ready-to-paste command"


# ── Job wiring ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("step", [
    "fetch_domestic_apifootball.py",     # the 12 expansion leagues' fixtures
    "import_history_apifootball.py",     # history-only league seasons
    "dedupe_fixtures.py",                # merge fixtures split by name drift
    "compute_predictions.py",
    "check_data_completeness.py",
])
def test_daily_still_runs_its_essential_steps(daily, step):
    """Guards against a step being dropped in a refactor.

    Each of these was added to fix a specific user-visible failure; silently
    losing one would not break anything loudly.
    """
    assert step in daily, f"{step} is no longer wired into run_daily.sh"


def test_warmup_stands_aside_for_the_heavy_jobs():
    """The 50-minute warm-up must not race the daily run's API budget.

    Locks are per-name, so `acquire_lock "run_warmup"` never excluded the daily
    job despite a comment claiming it did — and warm-ups landing inside the
    06:00 window failed 20 of 60 fixtures with HTTP 429.
    """
    warmup = _read("run_warmup.sh")
    assert "lock_held" in warmup, "run_warmup no longer checks the heavy jobs' locks"
    assert "run_daily" in warmup
