"""Forecast training and recursive prediction integration tests."""

from __future__ import annotations

import builtins

import pandas as pd
import pytest

from aiml.exceptions import SplitError
from aiml.forecasting.prediction import forecast_seven_day
from aiml.forecasting.training import select_and_train


def test_lightgbm_runtime_failure_falls_back_truthfully(
    daily_demand: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def fail_lightgbm(name, *args, **kwargs):
        if name == "lightgbm":
            raise OSError("simulated native DLL load failure")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_lightgbm)
    trained = select_and_train(daily_demand)
    assert trained.model_name == "seasonal_naive"
    assert "DLL" in trained.fallback_reason
    assert set(trained.validation_predictions["model_name"]) == {"seasonal_naive"}
    assert set(trained.validation_metrics) == {"mae", "wape", "bias"}
    assert {"seasonal_naive", "moving_average_28"} <= set(
        trained.model_validation_metrics
    )

    forecast = forecast_seven_day(
        daily_demand,
        trained,
        origin="2024-02-09",
    )
    assert len(forecast) == 2 * 7
    assert set(forecast["model_name"]) == {"seasonal_naive"}
    assert set(forecast["forecast_status"]) == {"ok"}
    assert (forecast["point_forecast"] >= 0).all()
    assert (forecast["forecast_date"] > forecast["forecast_origin"]).all()
    assert set(forecast["uncertainty_status"]) == {"estimated"}
    assert (forecast["lower_bound"] <= forecast["point_forecast"]).all()
    assert (forecast["point_forecast"] <= forecast["upper_bound"]).all()


def test_forecasting_rejects_history_without_a_valid_training_split() -> None:
    short = pd.DataFrame(
        {
            "sku_id": ["a", "a"],
            "destination_id": ["d", "d"],
            "demand_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "quantity": [1.0, 2.0],
        }
    )
    with pytest.raises(SplitError):
        select_and_train(short)
