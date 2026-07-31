"""
Outbound alerting — one helper, several webhook flavours.

`GATE_ALERT_URL` is the single alert sink for the whole project (dynamic-gate
promotions/demotions, API-Football pre-flight failures). It may point at:

  • ntfy      — https://ntfy.sh/<topic>   (phone push; no account needed)
  • Discord   — .../api/webhooks/...      (expects {"content": …})
  • Slack     — hooks.slack.com/...       (expects {"text": …})

ntfy needs different handling from the JSON webhooks: it takes the notification
body as the raw request body and everything else as X-* headers. Posting our JSON
there "works" but shows the reader a wall of raw JSON, so we format properly.

Everything here is best-effort and never raises — an alerting outage must not
break the pipeline that is trying to report a problem.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

TIMEOUT = 8

# Where the scheduled jobs write on the HOST.
#
# Left as a literal "~" on purpose: this module runs inside the container, where
# expanduser() would resolve to the container's home and hand the reader a path
# that doesn't exist on their Mac. The tilde is correct in the shell they will
# actually paste it into.
HOST_LOG_DIR = os.environ.get("ALERT_LOG_DIR", "~/Library/Logs/football-predictor")


def _is_ntfy(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "ntfy" in host


def post_alert(
    message: str,
    *,
    title: str | None = None,
    priority: str = "default",   # ntfy: min|low|default|high|urgent
    tags: str | None = None,     # ntfy: comma-separated emoji shortcodes
    click: str | None = None,    # ntfy: URL opened when the notification is tapped
    log: str | None = "daily.log",  # which log to read; None to omit
) -> bool:
    """POST `message` to GATE_ALERT_URL. Returns True when it was sent.

    No GATE_ALERT_URL configured → no-op returning False (callers still log).

    `log` appends a ready-to-paste tail command. An alert that says what broke
    but not where to read about it leaves you hunting through ~/Library/Logs at
    the worst possible moment. Paths are the HOST's — these run in a container,
    but the person reading the alert is at the Mac.
    """
    url = os.environ.get("GATE_ALERT_URL")
    if not url:
        return False

    if log:
        message = f"{message}\n\n📄 tail -120 {HOST_LOG_DIR}/{log}"

    try:
        import requests

        if _is_ntfy(url):
            headers: dict[str, str] = {}
            if title:
                # ntfy headers must be latin-1 encodable; emoji belong in Tags.
                headers["Title"] = title.encode("ascii", "replace").decode()
            if priority:
                headers["Priority"] = priority
            if tags:
                headers["Tags"] = tags
            if click:
                headers["Click"] = click
            requests.post(url, data=message.encode("utf-8"),
                          headers=headers, timeout=TIMEOUT)
        else:
            # {"content": …} suits Discord; Slack uses {"text": …}. Send both so a
            # single URL works for either without per-provider config.
            body = f"{title}\n{message}" if title else message
            requests.post(url, json={"content": body, "text": body}, timeout=TIMEOUT)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort, never raise
        print(f"  [alert] POST to GATE_ALERT_URL failed: {e}")
        return False
