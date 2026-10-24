"""Deterministic held-out allocation benchmark tests."""

from __future__ import annotations

import pandas as pd
import pytest

from aiml.evaluation.benchmark import run_benchmark
from aiml.optimization.eligibility import eligible_shipments


def test_benchmark_compares_optimizer_and_two_constrained_policies() -> None:
    inventory = pd.DataFrame(
        {
            "batch_id": ["b1", "b2"],
            "sku_id": ["s1", "s1"],
            "warehouse_id": ["w1", "w2"],
            "quantity": [6, 6],
            "expiry_date": pd.to_datetime(["2024-01-20", "2024-02-20"]),
        }
    )
    lanes = pd.DataFrame(
        {
            "warehouse_id": ["w1", "w2"],
            "destination_id": ["d1", "d1"],
            "is_available": [True, True],
            "transit_days": [1, 1],
        }
    )
    eligible = eligible_shipments(
        inventory, lanes, {"s1": 2}, origin_date="2024-01-01"
    )
    forecast = pd.DataFrame(
        {
            "sku_id": ["s1"],
            "destination_id": ["d1"],
            "point_forecast": [10],
        }
    )
    actual = pd.DataFrame(
        {
            "sku_id": ["s1"],
            "destination_id": ["d1"],
            "demand_date": pd.to_datetime(["2024-01-02"]),
            "quantity": [9],
        }
    )
    costs = pd.DataFrame(
        {
            "warehouse_id": ["w1", "w2"],
            "destination_id": ["d1", "d1"],
            "unit_transport_cost": [4, 1],
        }
    )

    result = run_benchmark(
        eligible,
        inventory,
        forecast,
        actual,
        transport_costs=costs,
        as_of="2024-01-01",
    )
    assert set(result.metrics["policy"]) == {
        "optiqo",
        "cheapest_first",
        "fefo_first",
    }
    assert result.optimizer_status == "optimal"
    assert result.metrics["actual_demand"].eq(9).all()
    assert result.metrics["unmet_demand"].eq(0).all()
    assert result.metrics["freight_cost"].notna().all()
    by_policy = result.metrics.set_index("policy")
    assert by_policy.loc["optiqo", "freight_cost"] == pytest.approx(22, abs=1e-5)
    assert by_policy.loc["cheapest_first", "freight_cost"] == pytest.approx(22)
    assert by_policy.loc["fefo_first", "freight_cost"] == pytest.approx(28)
    assert by_policy.loc["optiqo", "service_level"] == pytest.approx(1)
    assert result.metrics.loc[
        result.metrics["policy"] == "optiqo", "freight_cost"
    ].iloc[0] <= result.metrics.loc[
        result.metrics["policy"] == "cheapest_first", "freight_cost"
    ].iloc[0]
    cheapest_allocations = result.plans["cheapest_first"].set_index("batch_id")["allocated_quantity"]
    fefo_allocations = result.plans["fefo_first"].set_index("batch_id")["allocated_quantity"]
    assert not cheapest_allocations.equals(fefo_allocations)
    assert len(result.assumptions) >= 3
