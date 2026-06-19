"""
Entry point for national team model training.

Usage:
  python scripts/train_national.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.ml.national.train import train
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
MODELS_DIR = ROOT / "backend" / "data" / "models" / "national"

if __name__ == "__main__":
    train(DATA_DIR, MODELS_DIR)
