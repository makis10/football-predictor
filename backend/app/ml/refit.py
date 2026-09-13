"""Refit a booster at the tree count early stopping found, on all its rows.

Shared by the club and national trainers (backend/app/ml/train.py and
backend/app/ml/national/train.py). The national trainer never had it: its trees
shipped fitted on everything but the early-stopping fold — the newest 15% of the
rows it trained on — so the models it rebuilt every morning ended in 2018.
"""
from __future__ import annotations


def refit_on_everything(model, X_full, y_full, sample_weight, label: str):
    """Refit at the tree count early stopping discovered, on ALL the rows.

    Early stopping answers "how many trees" and costs a held-out fold to do it.
    Shipping the model fitted on `inner` alone throws that fold away — and the
    fold is the most recent data there is, which is the part that matters most
    for a football model.

    Returns a NEW estimator with early stopping disabled and n_estimators pinned
    to the discovered best. Falls back to the original model if the booster did
    not report one.
    """
    from sklearn.base import clone

    best = getattr(model, "best_iteration", None)
    if best is None:
        best = getattr(model, "best_iteration_", None)
    if best is None or best <= 0:
        print(f"  [{label}] no best_iteration reported — shipping the early-stopped fit")
        return model

    params = model.get_params()
    params["n_estimators"] = int(best) + 1
    # Set it to None, do NOT pop it: clone() carries the original's value, so
    # removing the key from this dict leaves early stopping switched on and the
    # refit dies with "Must have at least 1 validation dataset for early
    # stopping" — there is no eval_set here, by design.
    if "early_stopping_rounds" in params:
        params["early_stopping_rounds"] = None
    refit = clone(model).set_params(**params)
    refit.fit(X_full, y_full, sample_weight=sample_weight)
    print(f"  [{label}] refit on all {len(X_full):,} rows at {int(best) + 1} trees")
    return refit
