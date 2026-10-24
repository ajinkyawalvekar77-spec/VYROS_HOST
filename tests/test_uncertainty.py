"""Tests for held-out-residual forecast intervals."""

from __future__ import annotations

import numpy as np
import pytest

from aiml.forecasting.uncertainty import estimate_uncertainty


def test_uncertainty_interval_uses_validation_residuals() -> None:
    result = estimate_uncertainty(
        [10, 12, 11, 9, 12],
        [9, 12, 10, 10, 12],
        [0, 20],
        confidence_level=0.8,
        min_samples=5,
    )
    assert result["uncertainty_status"].tolist() == ["estimated", "estimated"]
    assert result.loc[0, "lower_bound"] == 0
    assert result.loc[0, "upper_bound"] >= 1
    assert np.all(result["lower_bound"] <= result["point_forecast"])


def test_uncertainty_is_explicit_when_residual_sample_is_too_small() -> None:
    result = estimate_uncertainty([2, 3], [1, 4], [5], min_samples=5)
    assert result.loc[0, "uncertainty_status"] == "insufficient_residuals"
    assert np.isnan(result.loc[0, "lower_bound"])
    assert np.isnan(result.loc[0, "upper_bound"])


def test_uncertainty_rejects_bad_configuration_and_values() -> None:
    with pytest.raises(ValueError, match="confidence_level"):
        estimate_uncertainty([1], [1], [1], confidence_level=1.0)
    with pytest.raises(ValueError, match="finite"):
        estimate_uncertainty([1], [float("inf")], [1])
