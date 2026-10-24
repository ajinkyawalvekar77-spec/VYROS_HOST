
"""Per-model forecast evaluation helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from ..evaluation.forecast_metrics import mae, wape, bias


def evaluate_forecasts(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
    *,
    model_name: str = "unknown",
) -> dict[str, Any]:
    """Evaluate forecast predictions using MAE, WAPE, and bias.

    Returns:
        A dictionary containing the model name, observation count,
        and forecast evaluation metrics.
    """
    try:
        y_true = np.asarray(actual, dtype=float)
        y_pred = np.asarray(predicted, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Actual and predicted values must be numeric.") from exc

    if y_true.ndim != 1 or y_pred.ndim != 1:
        raise ValueError("Actual and predicted values must be one-dimensional.")

    if y_true.size == 0:
        raise ValueError("At least one observation is required.")

    if y_true.size != y_pred.size:
        raise ValueError("Actual and predicted arrays must have equal lengths.")

    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a non-empty string.")

    return {
        "model_name": model_name.strip(),
        "n_observations": int(y_true.size),
        "mae": mae(y_true, y_pred),
        "wape": wape(y_true, y_pred),
        "bias": bias(y_true, y_pred),
    }


def compare_forecasts(
    actual: Sequence[float] | np.ndarray,
    forecasts: dict[str, Sequence[float] | np.ndarray],
) -> pd.DataFrame:
    """Compare multiple models and rank them by MAE."""
    if not forecasts:
        raise ValueError("At least one model forecast is required.")

    results = [
        evaluate_forecasts(actual, predictions, model_name=name)
        for name, predictions in forecasts.items()
    ]

    return (
        pd.DataFrame(results)
        .sort_values("mae", ascending=True)
        .reset_index(drop=True)
    )
