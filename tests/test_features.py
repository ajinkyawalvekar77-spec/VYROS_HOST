"""Leakage-safe feature tests."""

from __future__ import annotations

import pandas as pd

from aiml.config import EngineConfig, ForecastConfig
from aiml.forecasting.features import (
    LeakageSafeFeatureBuilder,
    add_calendar_lag_features,
    add_calendar_moving_average_feature,
    add_lag_features,
    add_rolling_features,
)


def _tiny_series() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sku_id": ["a"] * 4,
            "destination_id": ["d"] * 4,
            "demand_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "quantity": [10.0, 20.0, 30.0, 40.0],
        }
    )


def test_lag_features_use_only_past_values() -> None:
    frame = _tiny_series()
    out = add_lag_features(
        frame,
        group_columns=["sku_id", "destination_id"],
        date_column="demand_date",
        value_column="quantity",
        lags=(1, 2),
    )
    assert pd.isna(out.loc[0, "lag_1"])
    assert out.loc[1, "lag_1"] == 10.0
    assert out.loc[2, "lag_1"] == 20.0
    assert out.loc[3, "lag_1"] == 30.0
    assert out.loc[3, "lag_2"] == 20.0
    assert out.loc[3, "lag_1"] != 40.0


def test_rolling_features_exclude_the_current_target() -> None:
    frame = _tiny_series()
    out = add_rolling_features(
        frame,
        group_columns=["sku_id", "destination_id"],
        date_column="demand_date",
        value_column="quantity",
        windows=(2,),
    )
    # Shift then roll: row 2024-01-03 uses 10 and 20, not 30.
    assert out.loc[2, "rolling_mean_2"] == 15.0
    assert pd.isna(out.loc[0, "rolling_mean_2"])
    assert pd.isna(out.loc[1, "rolling_mean_2"])


def test_group_mean_is_fit_on_training_data_only(daily_demand: pd.DataFrame) -> None:
    train = daily_demand.loc[pd.to_datetime(daily_demand["demand_date"]) <= "2024-01-20"].copy()
    later = daily_demand.loc[pd.to_datetime(daily_demand["demand_date"]) > "2024-01-20"].copy()
    later = later.assign(quantity=999.0)
    builder = LeakageSafeFeatureBuilder(
        config=EngineConfig(forecast=ForecastConfig(lag_days=(1,), rolling_windows_days=(7,)))
    )
    builder.fit(train)
    combined = pd.concat([train, later], ignore_index=True)
    transformed = builder.transform(combined)
    later_rows = transformed.loc[transformed["demand_date"] > pd.Timestamp("2024-01-20")]
    expected = train.groupby(["sku_id", "destination_id"])["quantity"].mean()
    for _, row in later_rows.iterrows():
        assert row["train_group_mean"] == expected.loc[(row["sku_id"], row["destination_id"])]
        assert row["train_group_mean"] != 999.0


def test_calendar_features_come_from_the_row_date(daily_demand: pd.DataFrame) -> None:
    builder = LeakageSafeFeatureBuilder(
        config=EngineConfig(forecast=ForecastConfig(lag_days=(1,), rolling_windows_days=(7,)))
    )
    out = builder.fit_transform(daily_demand.loc[pd.to_datetime(daily_demand["demand_date"]) <= "2024-01-14"])
    sample = out.loc[out["demand_date"] == pd.Timestamp("2024-01-06")].iloc[0]
    # 2024-01-06 is a Saturday.
    assert int(sample["calendar_dow"]) == 5
    assert int(sample["calendar_is_weekend"]) == 1
    assert int(sample["calendar_month"]) == 1


def test_baseline_features_use_calendar_dates_without_bridging_gaps() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["a", "a", "a"],
            "destination_id": ["d", "d", "d"],
            "demand_date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-04"]
            ),
            "quantity": [1.0, 2.0, 4.0],
        }
    )
    lagged = add_calendar_lag_features(
        frame,
        group_columns=["sku_id", "destination_id"],
        date_column="demand_date",
        value_column="quantity",
        lags=(2,),
    )
    assert lagged.loc[2, "calendar_lag_2"] == 2.0

    averaged = add_calendar_moving_average_feature(
        frame,
        group_columns=["sku_id", "destination_id"],
        date_column="demand_date",
        value_column="quantity",
        window_days=3,
        min_periods=2,
    )
    assert pd.isna(averaged.loc[1, "calendar_rolling_mean_3"])
    assert averaged.loc[2, "calendar_rolling_mean_3"] == 1.5
