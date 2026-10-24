
"""MAE, WAPE, and bias with explicit zero-denominator handling."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _validate_inputs(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert inputs to arrays and validate paired demand values."""
    try:
        y_true = np.asarray(actual, dtype=float)
        y_pred = np.asarray(predicted, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Actual and predicted values must be numeric."
        ) from exc

    if y_true.ndim != 1 or y_pred.ndim != 1:
        raise ValueError(
            "Actual and predicted values must be one-dimensional."
        )

    if y_true.size == 0:
        raise ValueError("At least one observation is required.")

    if y_true.size != y_pred.size:
        raise ValueError(
            "Actual and predicted arrays must have equal lengths."
        )

    if not np.isfinite(y_true).all():
        raise ValueError("Actual values must be finite.")

    if not np.isfinite(y_pred).all():
        raise ValueError("Predicted values must be finite.")

    if (y_true < 0).any():
        raise ValueError("Actual demand cannot be negative.")

    if (y_pred < 0).any():
        raise ValueError("Predicted demand cannot be negative.")

    return y_true, y_pred


def mae(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
) -> float:
    """Return Mean Absolute Error in the original demand units."""
    y_true, y_pred = _validate_inputs(actual, predicted)

    return float(np.mean(np.abs(y_true - y_pred)))


def wape(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
) -> float | None:
    """Return Weighted Absolute Percentage Error as a ratio.

    Returns None when total actual demand is zero because WAPE is
    undefined in that case. Multiply a valid result by 100 to get
    a percentage.
    """
    y_true, y_pred = _validate_inputs(actual, predicted)

    denominator = float(np.sum(np.abs(y_true)))

    if denominator == 0:
        return None

    numerator = float(np.sum(np.abs(y_true - y_pred)))

    return numerator / denominator


def bias(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
) -> float:
    """Return mean signed forecast error: prediction minus actual.

    Positive bias indicates over-forecasting.
    Negative bias indicates under-forecasting.
    """
    y_true, y_pred = _validate_inputs(actual, predicted)

    return float(np.mean(y_pred - y_true))
