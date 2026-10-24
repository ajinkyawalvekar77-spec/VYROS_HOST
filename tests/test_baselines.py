"""Baseline predictor tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from aiml.config import EngineConfig, ForecastConfig
from aiml.forecasting.baselines import MovingAverageBaseline, SeasonalNaiveBaseline
from aiml.schemas import ForecastStatus


def test_seasonal_naive_uses_lag_seven_and_not_the_future(daily_demand: pd.DataFrame) -> None:
    origin = pd.Timestamp("2024-01-20")
    history = daily_demand.loc[pd.to_datetime(daily_demand["demand_date"]) <= origin].copy()
    history["demand_date"] = pd.to_datetime(history["demand_date"])
    model = SeasonalNaiveBaseline().fit(history)
    pred = model.predict(origin=origin, keys=pd.DataFrame({"sku_id": ["sku-a"], "destination_id": ["dest-1"]}))
    ok = pred.loc[pred["forecast_status"] == ForecastStatus.OK.value]
    assert len(ok) == 7
    history_idx = history.set_index(["sku_id", "destination_id", "demand_date"])["quantity"]
    for _, row in ok.iterrows():
        lagged = pd.Timestamp(row["forecast_date"]).normalize() - pd.Timedelta(days=7)
        assert lagged <= origin
        expected = float(history_idx.loc[("sku-a", "dest-1", lagged)])
        assert row["point_forecast"] == expected


def test_seasonal_naive_marks_insufficient_history() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["a"],
            "destination_id": ["d"],
            "demand_date": [date(2024, 1, 1)],
            "quantity": [5.0],
        }
    )
    pred = SeasonalNaiveBaseline().fit(frame).predict(origin="2024-01-01")
    # Horizon 7 looks back exactly to the origin date, which exists; earlier
    # horizons do not have a lag-7 observation.
    early = pred.loc[pred["horizon_day"] < 7]
    last = pred.loc[pred["horizon_day"] == 7].iloc[0]
    assert (early["forecast_status"] == ForecastStatus.INSUFFICIENT_HISTORY.value).all()
    assert early["point_forecast"].isna().all()
    assert last["forecast_status"] == ForecastStatus.OK.value
    assert last["point_forecast"] == 5.0


def test_moving_average_uses_origin_window_only(daily_demand: pd.DataFrame) -> None:
    origin = pd.Timestamp("2024-01-28")
    # Include later rows in the frame to catch look-ahead if the implementation leaks.
    model = MovingAverageBaseline().fit(daily_demand)
    pred = model.predict(origin=origin, keys=pd.DataFrame({"sku_id": ["sku-a"], "destination_id": ["dest-1"]}))
    window = daily_demand.loc[
        (daily_demand["sku_id"] == "sku-a")
        & (daily_demand["destination_id"] == "dest-1")
        & (pd.to_datetime(daily_demand["demand_date"]) >= origin - pd.Timedelta(days=27))
        & (pd.to_datetime(daily_demand["demand_date"]) <= origin)
    ]
    expected = float(window["quantity"].mean())
    future = daily_demand.loc[
        (daily_demand["sku_id"] == "sku-a")
        & (pd.to_datetime(daily_demand["demand_date"]) > origin)
    ]
    leaked_mean = float(pd.concat([window, future])["quantity"].mean())
    ok = pred.loc[pred["forecast_status"] == ForecastStatus.OK.value]
    assert len(ok) == 7
    assert ok["point_forecast"].nunique() == 1
    assert ok["point_forecast"].iloc[0] == pytest.approx(expected)
    assert ok["point_forecast"].iloc[0] != pytest.approx(leaked_mean)


def test_moving_average_insufficient_when_window_is_short() -> None:
    cfg = EngineConfig(
        forecast=ForecastConfig(moving_average_window_days=28, moving_average_min_periods=28, horizon_days=7)
    )
    frame = pd.DataFrame(
        {
            "sku_id": ["a"] * 5,
            "destination_id": ["d"] * 5,
            "demand_date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "quantity": [1.0, 0.0, 2.0, 3.0, 4.0],
        }
    )
    pred = MovingAverageBaseline(config=cfg).fit(frame).predict(origin="2024-01-05")
    assert (pred["forecast_status"] == ForecastStatus.INSUFFICIENT_HISTORY.value).all()


def test_zero_demand_is_a_valid_seasonal_observation() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["a"] * 8,
            "destination_id": ["d"] * 8,
            "demand_date": pd.date_range("2024-01-01", periods=8, freq="D"),
            "quantity": [1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0],
        }
    )
    pred = SeasonalNaiveBaseline().fit(frame).predict(origin="2024-01-08")
    day = pred.loc[pred["forecast_date"] == pd.Timestamp("2024-01-12")].iloc[0]
    # 2024-01-12 lags to 2024-01-05, which is zero.
    assert day["forecast_status"] == ForecastStatus.OK.value
    assert day["point_forecast"] == 0.0
