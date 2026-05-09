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
        depth=6,
        learning_rate=0.1,
        loss_function="RMSE",
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
        depth=6,
        learning_rate=0.1,
        loss_function="RMSE",
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
