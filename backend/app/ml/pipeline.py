"""
Full training pipeline — download data → engineer features → train → save models.

Can be called as a script or imported and invoked programmatically
(e.g. from the POST /admin/retrain endpoint in Phase 2).
"""

from __future__ import annotations

import subprocess
import sys
import os


def run_download():
    print("=" * 60)
    print("Step 1 — Downloading CSVs")
    print("=" * 60)
    script = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "scripts", "download_data.py"
    )
    result = subprocess.run([sys.executable, script], check=True)
    return result.returncode == 0


def run_train():
    print("\n" + "=" * 60)
    print("Step 2 — Training models")
    print("=" * 60)
    from backend.app.ml.train import main as train_main
    train_main()


def run_pipeline(skip_download: bool = False):
    """
    End-to-end pipeline.

    Args:
        skip_download: Set True if CSVs are already present and you only
                       want to retrain (faster for /admin/retrain endpoint).
    """
    if not skip_download:
        run_download()
    run_train()
    print("\nPipeline complete.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Football Predictor training pipeline")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip CSV download and use existing data",
    )
    args = parser.parse_args()
    run_pipeline(skip_download=args.skip_download)
