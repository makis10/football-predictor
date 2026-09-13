"""A running API process picks up a retrain.

The weekly retrain rewrites the model artifacts under the API process, which
loaded them once and kept serving the old ones until something restarted it —
nothing does. predict._get_models now reloads when any artifact changes, and a
reload must reach every cached piece: new models over old calibrators would be
worse than serving all of it stale.
"""
from __future__ import annotations

from backend.app.ml import btts_classifier, calibration, draw_classifier, predict


def test_a_changed_artifact_reloads_the_models_and_everything_fitted_with_them(monkeypatch):
    loads = []
    monkeypatch.setattr(predict, "_load_model", lambda name: loads.append(name) or object())
    monkeypatch.setattr(predict, "_result_model", None)
    monkeypatch.setattr(predict, "_goals_model", None)
    monkeypatch.setattr(predict, "_models_stamp", None)
    stamp = [100.0]
    monkeypatch.setattr(predict, "_artifacts_stamp", lambda: stamp[0])

    predict._get_models()
    predict._get_models()
    assert loads == ["model_result.pkl", "model_goals.pkl"], "unchanged files: no reload"

    monkeypatch.setattr(calibration, "_loaded", True)
    monkeypatch.setattr(draw_classifier, "_draw_loaded", True)
    monkeypatch.setattr(btts_classifier, "_btts_cal_loaded", True)
    stamp[0] = 200.0                          # the retrain wrote something
    predict._get_models()

    assert loads[2:] == ["model_result.pkl", "model_goals.pkl"]
    assert calibration._loaded is False
    assert draw_classifier._draw_loaded is False
    assert btts_classifier._btts_cal_loaded is False
