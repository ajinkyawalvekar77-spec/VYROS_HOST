"""Independent verification tests for allocation plans."""

from __future__ import annotations

import pandas as pd

from aiml.optimization.checker import verify_allocation
from aiml.optimization.eligibility import eligible_shipments


def _inputs():
    inventory = pd.DataFrame(
        {
            "batch_id": ["b1"],
            "sku_id": ["s1"],
            "warehouse_id": ["w1"],
            "quantity": [5],
            "expiry_date": pd.to_datetime(["2024-02-01"]),
        }
    )
    lanes = pd.DataFrame(
        {
            "warehouse_id": ["w1"],
            "destination_id": ["d1"],
            "is_available": [True],
            "transit_days": [2],
        }
    )
    candidates = eligible_shipments(
        inventory, lanes, {"s1": 3}, origin_date="2024-01-05"
    )
    plan = candidates.copy()
    plan["allocated_quantity"] = [4.0]
    plan["eligible_row_id"] = candidates.index
    capacity = pd.DataFrame({"destination_id": ["d1"], "capacity_units": [4]})
    forecast = pd.DataFrame(
        {"sku_id": ["s1"], "destination_id": ["d1"], "point_forecast": [4]}
    )
    return inventory, lanes, candidates, plan, capacity, forecast


def test_checker_accepts_valid_plan_and_recomputes_route_and_life() -> None:
    inventory, lanes, candidates, plan, capacity, forecast = _inputs()
    result = verify_allocation(
        plan,
        candidates,
        inventory,
        capacity,
        forecast,
        lanes=lanes,
        as_of="2024-01-05",
        sku_min_shelf_life_days={"s1": 3},
    )
    assert result.is_valid
    assert result.checks_failed == 0
    assert result.checks_not_run == []


def test_checker_rejects_stock_demand_capacity_and_route_violations() -> None:
    inventory, lanes, candidates, plan, _, forecast = _inputs()
    bad = plan.copy()
    bad.loc[0, "allocated_quantity"] = 7
    bad.loc[0, "destination_id"] = "missing"
    result = verify_allocation(
        bad,
        candidates,
        inventory,
        pd.DataFrame({"destination_id": ["d1"], "capacity_units": [4]}),
        forecast,
        lanes=lanes,
        as_of="2024-01-05",
        sku_min_shelf_life_days={"s1": 3},
    )
    failed = {entry["check"] for entry in result.violations}
    assert not result.is_valid
    assert "candidate_identity" in failed
    assert "stock_limit" in failed
    assert "available_route" in failed


def test_checker_reports_when_original_route_data_is_not_provided() -> None:
    inventory, _, candidates, plan, capacity, forecast = _inputs()
    result = verify_allocation(plan, candidates, inventory, capacity, forecast)
    assert not result.is_valid
    assert any("route availability" in note for note in result.checks_not_run)
