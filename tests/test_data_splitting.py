"""Chronological split tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from aiml.config import EngineConfig, SplitConfig
from aiml.exceptions import SplitError
from aiml.forecasting.data_splitting import split_chronologically


def test_explicit_cutoffs_are_strictly_chronological(daily_demand: pd.DataFrame) -> None:
    config = EngineConfig(
        split=SplitConfig(
            train_end=date(2024, 1, 20),
            validation_end=date(2024, 1, 30),
            test_end=date(2024, 2, 9),
        )
    )
    split = split_chronologically(daily_demand, config=config)
    assert split.train["demand_date"].max() == pd.Timestamp("2024-01-20")
    assert split.validation["demand_date"].min() == pd.Timestamp("2024-01-21")
    assert split.validation["demand_date"].max() == pd.Timestamp("2024-01-30")
    assert split.test["demand_date"].min() == pd.Timestamp("2024-01-31")
    assert split.test["demand_date"].max() == pd.Timestamp("2024-02-09")
    split.assert_no_overlap()


def test_fraction_split_has_no_date_overlap(daily_demand: pd.DataFrame) -> None:
    split = split_chronologically(daily_demand)
    train_dates = set(split.train["demand_date"])
    val_dates = set(split.validation["demand_date"])
    test_dates = set(split.test["demand_date"])
    assert train_dates.isdisjoint(val_dates)
    assert train_dates.isdisjoint(test_dates)
    assert val_dates.isdisjoint(test_dates)
    assert split.train["demand_date"].max() < split.validation["demand_date"].min()
    assert split.validation["demand_date"].max() < split.test["demand_date"].min()


def test_split_does_not_put_future_rows_in_train(daily_demand: pd.DataFrame) -> None:
    split = split_chronologically(daily_demand)
    demand = daily_demand.copy()
    demand["demand_date"] = pd.to_datetime(demand["demand_date"])
    future_after_train = demand.loc[demand["demand_date"] > split.train_end]
    train_keys = split.train[["sku_id", "destination_id", "demand_date"]]
    merged = future_after_train.merge(train_keys, on=["sku_id", "destination_id", "demand_date"], how="inner")
    assert len(merged) == 0


def test_non_monotonic_cutoffs_fail(daily_demand: pd.DataFrame) -> None:
    config = EngineConfig(
        split=SplitConfig(
            train_end=date(2024, 1, 30),
            validation_end=date(2024, 1, 10),
            test_end=date(2024, 2, 9),
        )
    )
    with pytest.raises(SplitError, match="train_end < validation_end < test_end"):
        split_chronologically(daily_demand, config=config)


def test_rows_after_test_end_are_not_silently_dropped(daily_demand: pd.DataFrame) -> None:
    config = EngineConfig(
        split=SplitConfig(
            train_end=date(2024, 1, 10),
            validation_end=date(2024, 1, 20),
            test_end=date(2024, 1, 25),
        )
    )
    with pytest.raises(SplitError, match="after test_end"):
        split_chronologically(daily_demand, config=config)
