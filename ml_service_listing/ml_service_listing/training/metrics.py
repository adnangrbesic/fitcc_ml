from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def compute_regression_metrics(
    y_true: Iterable[float],
    y_pred: Iterable[float],
) -> dict[str, float]:
    true_values = np.asarray(list(y_true), dtype=float)
    pred_values = np.asarray(list(y_pred), dtype=float)

    if true_values.size == 0:
        return {"mae": 0.0, "rmse": 0.0, "r2": 0.0, "within_0_5": 0.0, "within_1_0": 0.0}

    errors = pred_values - true_values
    mae = float(np.mean(np.abs(errors)))
    rmse = float(math.sqrt(np.mean(np.square(errors))))

    ss_res = float(np.sum(np.square(errors)))
    ss_tot = float(np.sum(np.square(true_values - np.mean(true_values))))
    r2 = 0.0 if ss_tot == 0.0 else 1.0 - ss_res / ss_tot

    within_0_5 = float(np.mean(np.abs(errors) <= 0.5))
    within_1_0 = float(np.mean(np.abs(errors) <= 1.0))

    return {
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "within_0_5": within_0_5,
        "within_1_0": within_1_0,
    }
