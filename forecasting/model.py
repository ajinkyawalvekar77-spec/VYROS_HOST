
"""LightGBM forecasting model for demand prediction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from ..exceptions import OptiqoAIMLError


class LightGBMUnavailableError(OptiqoAIMLError):
    """LightGBM could not be imported because its runtime is unavailable."""


def train_lightgbm_model(
    X_train: pd.DataFrame | np.ndarray,
    y_train: pd.Series | np.ndarray | list[float],
    *,
    params: Mapping[str, Any] | None = None,
    random_state: int = 42,
) -> Any:
    """Train and return a LightGBM regression model.

    Parameters
    ----------
    X_train:
        Training features. Each row represents one training observation.
    y_train:
        Non-negative numeric demand values corresponding to X_train rows.
    params:
        Optional LightGBM parameters. Supplied values override defaults.
    random_state:
        Seed used to make model training reproducible.

    Returns
    -------
    LGBMRegressor
        A fitted LightGBM regression model.

    Notes
    -----
    This function fits only on the data supplied to it. Chronological
    splitting and leakage-safe feature construction must happen before
    calling this function.
    """
    if not isinstance(X_train, (pd.DataFrame, np.ndarray)):
        raise TypeError("X_train must be a pandas DataFrame or NumPy array.")

    if isinstance(X_train, pd.DataFrame):
        if X_train.empty:
            raise ValueError("X_train must contain at least one row and feature.")

        if X_train.columns.has_duplicates:
            raise ValueError("X_train must not contain duplicate column names.")

        if not all(
            pd.api.types.is_numeric_dtype(dtype)
            for dtype in X_train.dtypes
        ):
            raise ValueError("All training features must be numeric.")

        feature_values = X_train.to_numpy(dtype=float)
    else:
        feature_values = np.asarray(X_train, dtype=float)

        if feature_values.ndim != 2:
            raise ValueError("X_train must be a two-dimensional array.")

        if feature_values.shape[0] == 0 or feature_values.shape[1] == 0:
            raise ValueError("X_train must contain rows and features.")

    # LightGBM supports NaN feature values, but not positive or negative infinity.
    if np.isinf(feature_values).any():
        raise ValueError("X_train must not contain infinite feature values.")

    try:
        target = np.asarray(y_train, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("y_train must contain numeric demand values.") from exc

    if target.ndim != 1:
        raise ValueError("y_train must be one-dimensional.")

    if target.size != feature_values.shape[0]:
        raise ValueError(
            "X_train and y_train must contain the same number of rows."
        )

    if target.size == 0:
        raise ValueError("y_train must not be empty.")

    if not np.isfinite(target).all():
        raise ValueError("y_train must contain only finite values.")

    if (target < 0).any():
        raise ValueError("Demand targets cannot be negative.")

    model_params: dict[str, Any] = {
        "objective": "regression",
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "random_state": random_state,
        "verbosity": -1,
        "n_jobs": -1,
    }

    if params is not None:
        if not isinstance(params, Mapping):
            raise TypeError("params must be a mapping of LightGBM parameters.")

        model_params.update(params)

    try:
        from lightgbm import LGBMRegressor
    except (ImportError, OSError) as exc:
        raise LightGBMUnavailableError(
            "LightGBM could not be loaded; use an explicitly identified baseline.",
            details={"cause": str(exc)},
        ) from exc

    model = LGBMRegressor(**model_params)
    model.fit(X_train, target)

    return model
