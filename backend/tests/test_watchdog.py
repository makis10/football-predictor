"""The watchdog must notice a dead API, not only a dead frontend.

2026-09-13: the backend's uvicorn worker died while its --reload supervisor
lived on. The container stayed "Up", every page rendered its empty state with
HTTP 200, and the watchdog — which probed only the frontend and could only run
`docker compose up -d` — had nothing to see and nothing to restart. The site
served no data for five minutes, until a manual restart.
"""
from __future__ import annotations

from pathlib import Path

WATCHDOG = Path(__file__).resolve().parents[2] / "scripts" / "run_watchdog.sh"


def _src() -> str:
    return WATCHDOG.read_text(encoding="utf-8")


def test_the_watchdog_probes_the_api_itself():
    assert "localhost:8000/health" in _src()


def test_a_dead_api_is_restarted_not_just_upped():
    src = _src()
    assert "docker compose restart backend" in src, (
        "`docker compose up -d` does nothing to a running container whose worker died")


def test_the_restart_never_lands_on_a_running_job():
    """A restart kills every `docker compose exec` step in flight — a retrain
    among them — so each scheduled job's lock must be checked first."""
    src = _src()
    block = src[src.index("BACKEND_STRIKES="):src.index("docker compose restart backend")]
    for job in ("run_daily", "run_prematch", "run_results_poll", "run_odds_poll", "run_warmup"):
        assert job in block, f"{job} can be killed mid-run by the API restart"
    assert "lock_held" in block


def test_one_failed_probe_is_not_enough():
    assert '"$strikes" -ge 2' in _src(), "a single slow response must not restart the API"
