
"""Residual-based uncertainty estimates for demand forecasts."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd


def estimate_uncertainty(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
    point_forecast: Sequence[float] | np.ndarray,
    *,
    confidence_level: float = 0.90,
    min_samples: int = 5,
) -> pd.DataFrame:
    """Estimate prediction intervals using validation-set residuals.

    Uses absolute validation residuals to estimate a symmetric interval
    around each future point forecast. The residual quantile uses a
    finite-sample correction similar to split conformal prediction.

    Parameters
    ----------
    actual:
        Actual demand values from a held-out validation period.
    predicted:
        Model predictions for those same validation observations.
    point_forecast:
        Future point forecasts for which intervals are required.
    confidence_level:
        Desired nominal coverage, strictly between 0 and 1.
    min_samples:
        Minimum number of finite validation residuals required.

    Returns
    -------
    pandas.DataFrame
        Columns:
        - point_forecast
        - lower_bound
        - upper_bound
        - interval_width
        - uncertainty_status

        If too few residuals are available, interval bounds and widths
        are NaN and uncertainty_status is "insufficient_residuals".

    Notes
    -----
    This is a marginal, residual-based interval estimate. It does not
    guarantee calibrated coverage for every SKU, destination, or horizon.
    Validation residuals should come from data not used to fit the model.
    """
    try:
        y_true = np.asarray(actual, dtype=float)
        y_pred = np.asarray(predicted, dtype=float)
        future = np.asarray(point_forecast, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("All inputs must contain numeric values.") from exc

    if y_true.ndim != 1 or y_pred.ndim != 1 or future.ndim != 1:
        raise ValueError("All inputs must be one-dimensional.")

    if y_true.size == 0:
        raise ValueError("Validation actual values cannot be empty.")

    if y_true.size != y_pred.size:
        raise ValueError(
            "Validation actual and predicted arrays must have equal lengths."
        )

    if future.size == 0:
        raise ValueError("At least one future point forecast is required.")

    if not np.isfinite(y_true).all() or not np.isfinite(y_pred).all():
        raise ValueError("Validation values must be finite.")

    if not np.isfinite(future).all():
        raise ValueError("Future point forecasts must be finite.")

    if (y_true < 0).any() or (y_pred < 0).any() or (future < 0).any():
        raise ValueError("Demand values and forecasts cannot be negative.")

    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1.")

    if isinstance(min_samples, bool) or not isinstance(min_samples, int):
        raise ValueError("min_samples must be a positive integer.")

    if min_samples < 1:
        raise ValueError("min_samples must be a positive integer.")

    residuals = np.abs(y_true - y_pred)
    sample_count = residuals.size

    result = pd.DataFrame({"point_forecast": future})

    if sample_count < min_samples:
        result["lower_bound"] = np.nan
        result["upper_bound"] = np.nan
        result["interval_width"] = np.nan
        result["uncertainty_status"] = "insufficient_residuals"
        return result

    # Finite-sample corrected quantile index for absolute residuals.
    quantile_rank = math.ceil((sample_count + 1) * confidence_level)
    quantile_rank = min(max(quantile_rank, 1), sample_count)

    radius = float(
        np.sort(residuals)[quantile_rank - 1]
    )

    lower = np.maximum(future - radius, 0.0)
    upper = future + radius

    result["lower_bound"] = lower
    result["upper_bound"] = upper
    result["interval_width"] = upper - lower
    result["uncertainty_status"] = "estimated"

    return result
