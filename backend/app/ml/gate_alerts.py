"""
Dynamic-gate change alerting.

When a market promotes into (or demotes out of) the headline suggestable set, the
only place it currently shows is /admin/markets — you have to go look. This emits
an alert the moment the proven set changes, so a promotion/demotion is noticed
when it happens.

Design mirrors the existing dead-man's-switch heartbeats: the previous proven set
is persisted to a small JSON file (durable across restarts and Redis flushes — a
30-min cache can't be the baseline), each fresh recompute diffs against it, and a
change is (a) logged prominently and (b) POSTed to GATE_ALERT_URL if that env var
is set (a Discord/Slack/ntfy-style webhook). No env var → log only. First-ever run
for a source seeds the baseline silently (nothing to diff against yet).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "gate_state.json"
# Append-only change log so the admin panel can show a history of promotions /
# demotions (the webhook is fire-and-forget; this is the durable record).
_HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "gate_changes.jsonl"
_HISTORY_MAX = 500                       # keep the file bounded; newest kept


def _load_state() -> dict:
    try:
        return json.loads(_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=0, sort_keys=True))
    except OSError as e:  # non-fatal — alerting must never break the pipeline
        print(f"  [gate-alert] could not persist state: {e}")


def _post_webhook(text: str) -> None:
    url = os.environ.get("GATE_ALERT_URL")
    if not url:
        return
    try:
        import requests
        # {"content": …} suits Discord; Slack uses {"text": …}. Send both keys so
        # a single URL works for either without per-provider config.
        requests.post(url, json={"content": text, "text": text}, timeout=8)
    except Exception as e:  # noqa: BLE001 — best-effort, never raise
        print(f"  [gate-alert] webhook POST failed: {e}")


def alert_gate_change(source: str, proven: Iterable[str]) -> Optional[dict]:
    """Diff `proven` for `source` against the last persisted set.

    Returns {"promoted": [...], "demoted": [...]} and fires log+webhook when the
    set changed; returns None (no alert) when unchanged or on first-ever seed.
    """
    new = sorted(set(proven))
    state = _load_state()
    prev = state.get(source)

    # Persist the new snapshot regardless, so the next run diffs against it.
    state[source] = new
    _save_state(state)

    if prev is None:                      # first observation → seed, don't alert
        return None
    prev_set = set(prev)
    new_set = set(new)
    if prev_set == new_set:
        return None

    promoted = sorted(new_set - prev_set)
    demoted = sorted(prev_set - new_set)
    parts = []
    if promoted:
        parts.append("promoted → " + ", ".join(promoted))
    if demoted:
        parts.append("demoted ✗ " + ", ".join(demoted))
    msg = f"🎯 [{source}] suggestable-market change: " + " | ".join(parts) \
          + f"  (now: {', '.join(new) or '∅'})"
    print(f"  {msg}")
    _post_webhook(msg)

    event = {
        "at":       datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source":   source,
        "promoted": promoted,
        "demoted":  demoted,
        "now":      new,
    }
    _append_history(event)
    return {"promoted": promoted, "demoted": demoted}


def _append_history(event: dict) -> None:
    """Append one change event to the JSONL log, trimmed to _HISTORY_MAX rows."""
    try:
        rows: list[str] = []
        if _HISTORY_PATH.exists():
            rows = [ln for ln in _HISTORY_PATH.read_text().splitlines() if ln.strip()]
        rows.append(json.dumps(event, ensure_ascii=False))
        rows = rows[-_HISTORY_MAX:]
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_PATH.write_text("\n".join(rows) + "\n")
    except OSError as e:  # non-fatal — never break the pipeline
        print(f"  [gate-alert] could not append history: {e}")


def load_history(limit: int = 100, source: Optional[str] = None) -> list[dict]:
    """Most-recent-first change events for the admin panel. Optional source filter."""
    try:
        lines = [ln for ln in _HISTORY_PATH.read_text().splitlines() if ln.strip()]
    except OSError:
        return []
    out: list[dict] = []
    for ln in lines:
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if source and row.get("source") != source:
            continue
        out.append(row)
    out.reverse()                          # newest first
    return out[:limit]
