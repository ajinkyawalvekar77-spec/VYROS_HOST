"""Task 1 tests for schema validation. Not listed in the target tree but required."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from aiml.exceptions import SchemaError, ValidationError
from aiml.schemas import (
    validate_capacities,
    validate_demand,
    validate_inventory_batches,
    validate_lanes,
    validate_transport_costs,
)


def test_demand_accepts_zero_and_rejects_negatives() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["a", "a"],
            "destination_id": ["d", "d"],
            "demand_date": [date(2024, 1, 1), date(2024, 1, 2)],
            "quantity": [0, 4],
        }
    )
    result = validate_demand(frame)
    assert result.row_count == 2
    assert result.frame["quantity"].tolist() == [0.0, 4.0]

    bad = frame.copy()
    bad.loc[0, "quantity"] = -1
    with pytest.raises(ValidationError, match="negative"):
        validate_demand(bad)


def test_demand_rejects_missing_columns_duplicates_and_bad_dates() -> None:
    with pytest.raises(SchemaError, match="missing required columns"):
        validate_demand(pd.DataFrame({"sku_id": ["a"]}))

    duplicates = pd.DataFrame(
        {
            "sku_id": ["a", "a"],
            "destination_id": ["d", "d"],
            "demand_date": [date(2024, 1, 1), date(2024, 1, 1)],
            "quantity": [1, 2],
        }
    )
    with pytest.raises(ValidationError, match="Duplicate"):
        validate_demand(duplicates)

    bad_date = pd.DataFrame(
        {
            "sku_id": ["a"],
            "destination_id": ["d"],
            "demand_date": ["not-a-date"],
            "quantity": [1],
        }
    )
    with pytest.raises(ValidationError, match="unparseable"):
        validate_demand(bad_date)


def test_demand_empty_frame_is_invalid() -> None:
    empty = pd.DataFrame(columns=["sku_id", "destination_id", "demand_date", "quantity"])
    with pytest.raises(ValidationError, match="no rows"):
        validate_demand(empty)


def test_inventory_does_not_drop_expired_batches() -> None:
    frame = pd.DataFrame(
        {
            "batch_id": ["b1", "b2"],
            "sku_id": ["a", "a"],
            "warehouse_id": ["w1", "w1"],
            "quantity": [5, 0],
            "expiry_date": [date(2020, 1, 1), date(2030, 1, 1)],
        }
    )
    result = validate_inventory_batches(frame)
    assert result.row_count == 2
    assert "expired" in " ".join(result.notes).lower() or "Expiry" in result.notes[0]


def test_inventory_rejects_negative_stock_without_clipping() -> None:
    frame = pd.DataFrame(
        {
            "batch_id": ["b1"],
            "sku_id": ["a"],
            "warehouse_id": ["w1"],
            "quantity": [-3],
        }
    )
    with pytest.raises(ValidationError, match="negative"):
        validate_inventory_batches(frame)


def test_lanes_keep_unavailable_rows() -> None:
    frame = pd.DataFrame(
        {
            "warehouse_id": ["w1", "w1"],
            "destination_id": ["d1", "d2"],
            "is_available": [True, False],
            "transit_days": [1, 2],
        }
    )
    result = validate_lanes(frame)
    assert result.row_count == 2
    assert bool(result.frame["is_available"].tolist() == [True, False])


def test_lanes_reject_unknown_availability_tokens() -> None:
    frame = pd.DataFrame(
        {
            "warehouse_id": ["w1"],
            "destination_id": ["d1"],
            "is_available": ["maybe"],
        }
    )
    with pytest.raises(ValidationError, match="boolean"):
        validate_lanes(frame)


def test_transport_costs_and_capacities_reject_negatives() -> None:
    costs = pd.DataFrame(
        {
            "warehouse_id": ["w1"],
            "destination_id": ["d1"],
            "unit_transport_cost": [-0.5],
        }
    )
    with pytest.raises(ValidationError, match="negative"):
        validate_transport_costs(costs)

    caps = pd.DataFrame({"destination_id": ["d1"], "capacity_units": [-1]})
    with pytest.raises(ValidationError, match="negative"):
        validate_capacities(caps)


def test_capacities_zero_is_allowed() -> None:
    caps = pd.DataFrame({"destination_id": ["d1"], "capacity_units": [0]})
    result = validate_capacities(caps)
    assert result.frame["capacity_units"].iloc[0] == 0.0


def test_non_finite_demand_and_duplicate_batches_are_rejected() -> None:
    demand = pd.DataFrame(
        {
            "sku_id": ["a"],
            "destination_id": ["d"],
            "demand_date": [date(2024, 1, 1)],
            "quantity": [float("inf")],
        }
    )
    with pytest.raises(ValidationError, match="non-finite"):
        validate_demand(demand)

    batches = pd.DataFrame(
        {
            "batch_id": ["b1", "b1"],
            "sku_id": ["a", "a"],
            "warehouse_id": ["w", "w"],
            "quantity": [2, 3],
        }
    )
    with pytest.raises(ValidationError, match="Duplicate"):
        validate_inventory_batches(batches)
