from __future__ import annotations

from typing import Any

import pandas as pd


def train_catboost_regressor(
    dataset: pd.DataFrame,
    target_column: str,
    cat_features: list[str],
) -> Any:
    try:
        from catboost import CatBoostRegressor
    except ImportError as exc:
        raise RuntimeError("catboost is required for training") from exc

    X = dataset.drop(columns=[target_column])
    y = dataset[target_column]

    model = CatBoostRegressor(
        iterations=500,
        depth=6,
        learning_rate=0.1,
        loss_function="RMSE",
        verbose=False,
    )
    model.fit(X, y, cat_features=cat_features)
    return model


def save_model(model: Any, path: str) -> None:
    model.save_model(path)
