"""
Pre-flight check for API-Football access — run FIRST in run_daily.sh.

Why this exists
---------------
The account uses an IP whitelist and the home connection has a dynamic IP.
When the IP rotates, every API-Football call returns

    {"errors": {"Ip": "This IP is not allowed to call the API, ..."}}

with HTTP 200. Nothing raises, so each caller just logs a warning and moves on:
the cron job finishes with exit 0 while having fetched nothing. In July 2026 that
went unnoticed for five days — no CL fixtures, no results, stale club/player
stats — and the retry/backoff on ~7,400 blocked calls stretched the daily run
from ~15 minutes to over four hours.

This check turns that silent failure into a loud one:
  • prints a banner with the CURRENT public IP (the value to paste into the
    API-Football dashboard whitelist),
  • POSTs the same information to GATE_ALERT_URL when configured (the existing
    alerting channel — see backend/app/ml/gate_alerts.py),
  • exits 2 so the caller can skip the API-heavy steps instead of burning hours
    retrying calls that cannot succeed.

Exit codes:
    0  API reachable (prints remaining quota)
    2  IP not whitelisted  → whitelist the printed IP
    3  other API/auth error (bad key, plan expired, network down)
"""
from __future__ import annotations


import os
import sys


import requests

API_BASE = "https://v3.football.api-sports.io"
TIMEOUT = 20


def current_public_ip() -> str:
    """Public egress IP as the API sees us. Best-effort — never raises."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            return requests.get(url, timeout=8).text.strip()
        except Exception:
            continue
    return "unknown"


def send_alert(message: str, *, title: str, priority: str = "urgent",
               tags: str = "rotating_light", click: str | None = None) -> None:
    """Push through the shared sink (ntfy / Discord / Slack). Never raises."""
    from backend.app.alerting import post_alert

    if post_alert(message, title=title, priority=priority, tags=tags, click=click):
        print("  [alert] pushed to GATE_ALERT_URL")
    else:
        print("  [alert] GATE_ALERT_URL not set — logged only")


def banner(lines: list[str]) -> None:
    width = max(len(line) for line in lines) + 4
    print("!" * width)
    for line in lines:
        print(f"! {line.ljust(width - 4)} !")
    print("!" * width)


def main() -> int:
    key = os.getenv("API_SPORTS_KEY", "")
    if not key:
        banner(["API-Football PRE-FLIGHT FAILED",
                "API_SPORTS_KEY is not set in the environment."])
        return 3

    try:
        data = requests.get(f"{API_BASE}/status",
                            headers={"x-apisports-key": key},
                            timeout=TIMEOUT).json()
    except Exception as exc:
        banner(["API-Football PRE-FLIGHT FAILED",
                f"Could not reach {API_BASE}: {exc}"])
        return 3

    errors = data.get("errors") or {}
    # A healthy response returns errors as an empty list; failures use a dict.
    if isinstance(errors, dict) and errors:
        if "Ip" in errors:
            ip = current_public_ip()
            banner([
                "API-Football BLOCKED — IP NOT WHITELISTED",
                "",
                f"Current public IP: {ip}",
                "",
                "Every API-Football call will return no data until this IP is",
                "added at https://dashboard.api-football.com (IP whitelist).",
                "Affected: CL/EL/ECL fixtures + results, club friendlies,",
                "club team/player stats, injuries, squad strength.",
            ])
            send_alert(
                f"Whitelist this IP:\n\n{ip}\n\n"
                "Until then: no CL/EL/ECL fixtures or results, no club friendlies "
                "results, no club/player stats, no injuries.",
                title="API-Football blocked - IP changed",
                priority="urgent",
                tags="rotating_light",
                click="https://dashboard.api-football.com",
            )
            return 2

        banner(["API-Football PRE-FLIGHT FAILED", f"errors: {errors}"])
        send_alert(f"API-Football error: {errors}",
                   title="API-Football pre-flight failed",
                   priority="high", tags="warning")
        return 3

    resp = data.get("response") or {}
    sub = resp.get("subscription") or {}
    req = resp.get("requests") or {}
    print(f"  API-Football OK — plan={sub.get('plan')} "
          f"requests={req.get('current')}/{req.get('limit_day')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
