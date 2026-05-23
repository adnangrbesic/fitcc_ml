from __future__ import annotations

from pathlib import Path
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
        depth=5,               # Reduced from 6 — less overfitting on sparse data
        learning_rate=0.05,    # Reduced from 0.1 — more conservative learning
        l2_leaf_reg=3.0,       # L2 regularization to prevent overfitting
        loss_function="RMSE",
        early_stopping_rounds=50,  # Stop early if no improvement for 50 rounds
        verbose=False,
    )
    model.fit(X, y, cat_features=cat_features)
    return model


def save_model(model: Any, path: str) -> None:
    file_path = Path(path)
    _ensure_parent_dir(file_path)
    model.save_model(str(file_path))


def load_model(path: str) -> Any | None:
    try:
        from catboost import CatBoostRegressor
    except ImportError as exc:
        raise RuntimeError("catboost is required for training") from exc

    file_path = Path(path)
    if not file_path.exists() or file_path.is_dir():
        return None

    model = CatBoostRegressor()
    model.load_model(str(file_path))
    return model


def continue_training(
    dataset: pd.DataFrame,
    target_column: str,
    cat_features: list[str],
    model_path: str,
    iterations: int = 50,
) -> Any:
    try:
        from catboost import CatBoostRegressor
    except ImportError as exc:
        raise RuntimeError("catboost is required for training") from exc

    X = dataset.drop(columns=[target_column])
    y = dataset[target_column]
    init_model = load_model(model_path)

    model = CatBoostRegressor(
        iterations=iterations,
        depth=5,               # Matches train_catboost_regressor
        learning_rate=0.05,
        l2_leaf_reg=3.0,
        loss_function="RMSE",
        early_stopping_rounds=20,
        verbose=False,
    )

    if init_model is not None:
        model.fit(X, y, cat_features=cat_features, init_model=init_model)
    else:
        model.fit(X, y, cat_features=cat_features)

    save_model(model, model_path)
    return model


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    if parent.exists():
        if not parent.is_dir():
            raise RuntimeError(f"Model path parent is not a directory: {parent}")
        return
    parent.mkdir(parents=True, exist_ok=True)
