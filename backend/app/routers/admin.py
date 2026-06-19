"""
Admin endpoints — protected by ADMIN_API_KEY env var.
POST /admin/retrain  →  trigger model retraining
GET  /admin/retrain/status  →  check if retraining is in progress

Set ADMIN_API_KEY in .env.  Pass as X-Admin-Key request header.
"""

import logging
import os
import subprocess
import sys
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel

log = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])

_ADMIN_KEY = os.getenv("ADMIN_API_KEY", "")

# Thread-safe retrain lock — prevents concurrent retrains.
_retrain_lock = threading.Lock()
_retraining_in_progress = False


def _require_admin_key(x_admin_key: str = Header(default="")) -> None:
    """Dependency: validate X-Admin-Key header against ADMIN_API_KEY env var."""
    if not _ADMIN_KEY:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_API_KEY not configured on the server. Set it in .env.",
        )
    if x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key.")


class RetrainResponse(BaseModel):
    status: str
    message: str


def _reload_all_models() -> None:
    """
    Reset all in-memory model singletons so the next prediction request
    reloads the freshly-trained files from disk.
    Called at the end of _do_retrain() to ensure the running process picks
    up the new models without requiring a process restart.
    """
    try:
        from backend.app.ml.calibration import reload_calibrators
        from backend.app.ml.draw_classifier import reload_draw_models
        from backend.app.ml.btts_classifier import reload_btts_models
        from backend.app.ml import predict as _predict_mod

        reload_calibrators()
        reload_draw_models()
        reload_btts_models()

        # Reset result/goals model singletons in predict.py
        _predict_mod._result_model = None
        _predict_mod._goals_model  = None
        _predict_mod._DRAW_ALPHA   = None
        _predict_mod._BTTS_THRESHOLD = None
        _predict_mod._european_df  = None
        log.info("[admin] All model singletons cleared — will reload on next request.")
    except Exception as e:
        log.warning("[admin] Could not clear model singletons: %s", e)


def _do_retrain(skip_download: bool = False):
    """Background worker: optionally download fresh data, then train + reload.

    Runs entirely off the request thread so the HTTP call returns immediately
    (the data download alone can take minutes). Progress goes to the logs.
    """
    global _retraining_in_progress
    try:
        if not skip_download:
            script = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "..", "scripts", "download_data.py"
            )
            try:
                subprocess.run([sys.executable, script], check=True, timeout=600)
            except Exception as e:
                log.error("[admin] Retrain aborted — data download failed: %s", e)
                return
        from backend.app.ml.train import main as train_main
        train_main()
        _reload_all_models()
    finally:
        with _retrain_lock:
            _retraining_in_progress = False


@router.post("/retrain", response_model=RetrainResponse,
             dependencies=[Depends(_require_admin_key)])
def retrain(background_tasks: BackgroundTasks, skip_download: bool = False):
    global _retraining_in_progress

    with _retrain_lock:
        if _retraining_in_progress:
            raise HTTPException(status_code=409, detail="Retraining already in progress")
        _retraining_in_progress = True

    # Download + train both run in the background so the request returns at once.
    background_tasks.add_task(_do_retrain, skip_download)

    return RetrainResponse(
        status="accepted",
        message="Retraining started in the background. Check logs for progress.",
    )


@router.get("/retrain/status", response_model=RetrainResponse,
            dependencies=[Depends(_require_admin_key)])
def retrain_status():
    with _retrain_lock:
        in_progress = _retraining_in_progress
    if in_progress:
        return RetrainResponse(status="in_progress", message="Retraining is running.")
    return RetrainResponse(status="idle", message="No retraining in progress.")
