"""Serving must see the same frame training was fitted on.

train.py calls merge_xg() before build_features, so 43% of the rows the model
learned from carry real Understat rolling xG. Neither serving path did: both
loaded the raw CSVs alone, which have no xG columns at all, so
build_team_snapshot's xG deques stayed empty and all eight xG features arrived
as NaN on 100% of served fixtures — then filled with the global training median.

The model was reading a constant where it had been taught to read a signal.
Measured 2026-09-03 over 969 replayed matches, restoring the merge cut the
train/serve divergence in the argmax pick from 4.33% to 1.34%.

This is a parity test, not a performance one. On the 419 xG-covered rows the
accuracy difference was +0.7pp with a standard error of 2.4pp — nowhere near
significant. The justification is that serving and training disagree, which is a
defect whatever it scores.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Every module that builds a history frame the model will be predicted from.
_SERVING_LOADERS = [
    _ROOT / "scripts" / "compute_predictions.py",
    _ROOT / "backend" / "app" / "routers" / "predictions.py",
]


def _calls(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


@pytest.mark.parametrize("path", _SERVING_LOADERS, ids=lambda p: p.name)
def test_every_serving_path_merges_xg(path: pathlib.Path):
    if not path.exists():
        pytest.skip(f"{path} not present")
    calls = _calls(path)
    if "load_raw_csvs" not in calls:
        pytest.skip(f"{path.name} no longer loads a history frame")
    assert "merge_xg" in calls, (
        f"{path.name} loads raw CSVs but never calls merge_xg(), so every xG "
        f"feature will be NaN at serve time and filled with the training "
        f"median — while the model was fitted on real values. Load the xG frame "
        f"with load_xg_data(XG_DIR) and merge it, as train.py does."
    )


def test_training_still_merges_xg():
    """If training ever stops merging, the tests above become the wrong rule."""
    calls = _calls(_ROOT / "backend" / "app" / "ml" / "train.py")
    assert "merge_xg" in calls, (
        "train.py no longer merges xG — the serving-parity assertions above now "
        "enforce the opposite of what training does. Fix them together."
    )
