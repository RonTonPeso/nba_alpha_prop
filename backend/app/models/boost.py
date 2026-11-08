"""One fixed XGBoost configuration per prop.

The first fit does not search. Hyperparameters stay off the holdout.
The stored spread is the training residual of the shipped (clipped) mean,
not a posterior. SHAP values come from XGBoost's tree contributions.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np
import xgboost as xgb

from app.models.baseline import _Z10, _Z90, STD_FLOOR

MODEL_VERSION = "xgb-m5-v1"

N_ESTIMATORS = 200
MAX_DEPTH = 4
LEARNING_RATE = 0.05
SUBSAMPLE = 0.8
COLSAMPLE_BYTREE = 0.8
MIN_CHILD_WEIGHT = 5
REG_LAMBDA = 1.0
RANDOM_STATE = 0


def hyperparameters() -> dict[str, object]:
    return {
        "num_boost_round": N_ESTIMATORS,
        "max_depth": MAX_DEPTH,
        "eta": LEARNING_RATE,
        "subsample": SUBSAMPLE,
        "colsample_bytree": COLSAMPLE_BYTREE,
        "min_child_weight": MIN_CHILD_WEIGHT,
        "lambda": REG_LAMBDA,
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "seed": RANDOM_STATE,
        "nthread": 1,
    }


def _matrix(features: Any, target: Any | None = None) -> xgb.DMatrix:
    frame = np.asarray(features, dtype=np.float64)
    if target is None:
        return xgb.DMatrix(frame)
    return xgb.DMatrix(frame, label=np.asarray(target, dtype=np.float64))


def fit_regressor(features: Any, target: Any) -> xgb.Booster:
    """Fit on training rows only. The caller must not pass holdout rows."""
    params = {key: value for key, value in hyperparameters().items() if key != "num_boost_round"}
    return xgb.train(params, _matrix(features, target), num_boost_round=N_ESTIMATORS)


def predict(model: xgb.Booster, features: Any) -> list[float]:
    return [float(value) for value in model.predict(_matrix(features))]


def shipped_mean(raw: float) -> float:
    """Counting stats are not negative. The stored mean is clipped at 0."""
    return max(0.0, raw)


def residual_std(actual: list[float], predicted: list[float]) -> float:
    """Sample spread of training residuals around the shipped mean.

    Fewer than two rows, or a perfect fit, still gets the baseline floor
    so the probability tail has a positive width.
    """
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted must be the same length")
    if len(actual) < 2:
        return STD_FLOOR
    residuals = [y - shipped_mean(pred) for y, pred in zip(actual, predicted, strict=True)]
    return max(statistics.stdev(residuals), STD_FLOOR)


def probability_band(mean: float, std: float) -> tuple[float, float, float]:
    """10th, 50th, and 90th percentiles of the residual normal. The 10th is clipped at 0."""
    if std <= 0:
        raise ValueError(f"std must be positive, got {std}")
    center = shipped_mean(mean)
    return (
        max(0.0, center + _Z10 * std),
        center,
        center + _Z90 * std,
    )


def shap_top(
    model: xgb.Booster,
    features: Any,
    names: tuple[str, ...],
    *,
    limit: int = 5,
) -> list[list[tuple[str, float]]]:
    """Top contributions per row, largest absolute value first.

    The bias column from ``pred_contribs`` is dropped. Ties break on the
    feature name so a rerun stores the same order.
    """
    matrix = np.asarray(features, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(names):
        raise ValueError("feature matrix does not match names")
    frame = xgb.DMatrix(matrix, feature_names=list(names))
    contribs = np.asarray(model.predict(frame, pred_contribs=True), dtype=np.float64)
    if contribs.shape[1] != len(names) + 1:
        raise ValueError("pred_contribs did not return one column per feature plus bias")
    ranked: list[list[tuple[str, float]]] = []
    keep = min(limit, len(names))
    for row in contribs:
        order = sorted(range(len(names)), key=lambda index: (-abs(float(row[index])), names[index]))
        ranked.append([(names[index], float(row[index])) for index in order[:keep]])
    return ranked
