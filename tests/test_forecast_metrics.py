"""Tests for MAE, WAPE, and forecast bias."""

from __future__ import annotations

import pytest

from aiml.evaluation.forecast_metrics import bias, mae, wape


def test_metrics_have_documented_units_and_direction() -> None:
    actual = [10.0, 20.0, 0.0]
    predicted = [12.0, 16.0, 2.0]
    assert mae(actual, predicted) == pytest.approx(8 / 3)
    assert wape(actual, predicted) == pytest.approx(8 / 30)
    assert bias(actual, predicted) == pytest.approx(0.0)


def test_wape_is_undefined_for_zero_actual_total() -> None:
    assert wape([0.0, 0.0], [0.0, 3.0]) is None


@pytest.mark.parametrize(
    ("actual", "predicted"),
    [([], []), ([1.0], [1.0, 2.0]), ([float("nan")], [1.0]), ([1.0], [-1.0])],
)
def test_metrics_reject_invalid_inputs(actual, predicted) -> None:
    with pytest.raises(ValueError):
        mae(actual, predicted)
