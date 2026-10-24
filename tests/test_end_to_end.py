"""Deterministic forecasting-to-allocation integration test."""

from __future__ import annotations

import builtins

import pandas as pd
import pytest

from aiml.evaluation.benchmark import run_benchmark
from aiml.forecasting.prediction import forecast_seven_day
from aiml.forecasting.training import select_and_train
from aiml.optimization.checker import verify_allocation
from aiml.optimization.eligibility import eligible_shipments
from aiml.optimization.explanations import explain_allocation
from aiml.optimization.optimizer import optimize_allocation


def test_full_forecast_allocation_verification_explanation_benchmark(
    daily_demand: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def fail_lightgbm(name, *args, **kwargs):
        if name == "lightgbm":
            raise OSError("deterministic test fallback")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_lightgbm)
    training = select_and_train(daily_demand)
    forecasts = forecast_seven_day(daily_demand, training, origin="2024-02-09")

    inventory = pd.DataFrame(
        {
            "batch_id": ["stock-a"],
            "sku_id": ["sku-a"],
            "warehouse_id": ["warehouse-a"],
            "quantity": [100.0],
            "expiry_date": [pd.Timestamp("2024-12-31")],
        }
    )
    lanes = pd.DataFrame(
        {
            "warehouse_id": ["warehouse-a"],
            "destination_id": ["dest-1"],
            "is_available": [True],
            "transit_days": [2],
        }
    )
    candidates = eligible_shipments(
        inventory,
        lanes,
        {"sku-a": 7},
        origin_date="2024-02-09",
    )
    capacity = pd.DataFrame(
        {"destination_id": ["dest-1"], "capacity_units": [100]}
    )
    costs = pd.DataFrame(
        {
            "warehouse_id": ["warehouse-a"],
            "destination_id": ["dest-1"],
            "unit_transport_cost": [2.5],
        }
    )
    allocation = optimize_allocation(
        candidates,
        inventory,
        capacity,
        forecasts,
        costs,
        as_of="2024-02-09",
    )
    assert allocation.status == "optimal"
    assert allocation.plan["allocated_quantity"].sum() <= 100

    verification = verify_allocation(
        allocation.plan,
        candidates,
        inventory,
        capacity,
        forecasts,
        lanes=lanes,
        as_of="2024-02-09",
        sku_min_shelf_life_days={"sku-a": 7},
    )
    assert verification.is_valid
    explanations = explain_allocation(
        allocation.plan, candidates, inventory, capacity, forecasts, costs
    )
    assert len(explanations) == len(candidates)
    assert explanations.loc[0, "batch_stock"] == 100
    assert explanations.loc[0, "unit_transport_cost"] == 2.5

    held_out = pd.DataFrame(
        {
            "sku_id": ["sku-a"],
            "destination_id": ["dest-1"],
            "demand_date": [pd.Timestamp("2024-02-10")],
            "quantity": [35.0],
        }
    )
    benchmark = run_benchmark(
        candidates,
        inventory,
        forecasts,
        held_out,
        capacities=capacity,
        transport_costs=costs,
        as_of="2024-02-09",
    )
    assert benchmark.optimizer_status == "optimal"
    assert len(benchmark.metrics) == 3
    assert benchmark.metrics["unmet_demand"].notna().all()
