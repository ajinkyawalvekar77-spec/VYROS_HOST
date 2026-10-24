"""Batch eligibility and route/shelf-life edge-case tests."""

from __future__ import annotations

import pandas as pd
import pytest

from aiml.exceptions import SchemaError, ValidationError
from aiml.optimization.eligibility import eligible_shipments


def _inventory() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "batch_id": ["soon", "good", "no-stock"],
            "sku_id": ["s", "s", "s"],
            "warehouse_id": ["w", "w", "w"],
            "quantity": [8, 5, 0],
            "expiry_date": pd.to_datetime(["2024-01-12", "2024-02-01", "2024-03-01"]),
        }
    )


def _lanes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "warehouse_id": ["w", "w"],
            "destination_id": ["d", "blocked"],
            "is_available": [True, False],
            "transit_days": [3, 1],
        }
    )


def test_eligibility_respects_route_stock_and_arrival_shelf_life() -> None:
    result = eligible_shipments(
        _inventory(), _lanes(), {"s": 5}, origin_date="2024-01-05"
    )
    assert result["batch_id"].tolist() == ["good"]
    assert result.iloc[0]["destination_id"] == "d"
    assert result.iloc[0]["remaining_shelf_life_days_at_arrival"] >= 5
    assert result.iloc[0]["expiry_date"] == pd.Timestamp("2024-02-01")


def test_zero_stock_and_ineligible_batches_produce_empty_candidates() -> None:
    inventory = _inventory().iloc[[2]].copy()
    result = eligible_shipments(
        inventory, _lanes(), {"s": 0}, origin_date="2024-01-05"
    )
    assert result.empty
    assert "batch_id" in result.columns


def test_eligibility_requires_transit_and_shelf_life_evidence() -> None:
    with pytest.raises(SchemaError, match="transit_days"):
        eligible_shipments(
            _inventory(),
            _lanes().drop(columns="transit_days"),
            {"s": 0},
            origin_date="2024-01-05",
        )
    with pytest.raises(SchemaError, match="expiry_date"):
        eligible_shipments(
            _inventory().drop(columns="expiry_date"),
            _lanes(),
            {"s": 0},
            origin_date="2024-01-05",
        )


def test_duplicate_lane_and_invalid_shelf_life_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate"):
        eligible_shipments(
            _inventory(),
            pd.concat([_lanes(), _lanes().iloc[[0]]], ignore_index=True),
            {"s": 0},
            origin_date="2024-01-05",
        )
    with pytest.raises(ValueError, match="non-negative integer"):
        eligible_shipments(_inventory(), _lanes(), {"s": -1}, origin_date="2024-01-05")
