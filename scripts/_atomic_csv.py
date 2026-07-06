"""Crash-safe CSV writes shared by the dataset-sync scripts.

Writing straight to the target path (df.to_csv(path)) leaves a truncated/
corrupt file if the process is killed mid-write (e.g. the Mac sleeping or
shutting down partway through a launchd run). Writing to a temp file in the
same directory and os.replace()-ing it onto the target is atomic on the same
filesystem, so the target is either the old file or the fully-written new one.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


def atomic_to_csv(df: pd.DataFrame, path: Path, **kwargs) -> None:
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            df.to_csv(f, **kwargs)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise
