"""Reproducible demo workflow using the public Optiqo engine functions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping

import pandas as pd

from .config import EngineConfig
from .evaluation.benchmark import BenchmarkResult, run_benchmark
from .forecasting.prediction import forecast_seven_day
from .forecasting.training import TrainingResult, select_and_train
from .optimization.checker import AllocationCheckResult, verify_allocation
from .optimization.eligibility import eligible_shipments
from .optimization.explanations import explain_allocation
from .optimization.optimizer import AllocationResult, optimize_allocation
from .schemas import validate_demand


@dataclass
class DemoResult:
    training: TrainingResult
    forecast: pd.DataFrame
    allocation: AllocationResult
    verification: AllocationCheckResult
    explanations: pd.DataFrame
    benchmark: BenchmarkResult


def run_demo_workflow(
    demand_history: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    lanes: pd.DataFrame,
    sku_min_shelf_life_days: Mapping[str, int],
    capacities: pd.DataFrame,
    transport_costs: pd.DataFrame,
    held_out_actuals: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> DemoResult:
    """Run the full engine path on caller-supplied frames."""
    cfg = config or EngineConfig()
    demand = validate_demand(demand_history, config=cfg).frame
    origin = demand[cfg.columns.demand_date].max().normalize()

    training = select_and_train(demand, config=cfg)
    forecast = forecast_seven_day(
        demand,
        training,
        origin=origin,
        config=cfg,
    )
    candidates = eligible_shipments(
        inventory_batches,
        lanes,
        sku_min_shelf_life_days,
        origin_date=origin,
        config=cfg,
    )
    allocation = optimize_allocation(
        candidates,
        inventory_batches,
        capacities,
        forecast,
        transport_costs,
        config=cfg,
        as_of=origin,
    )
    verification = verify_allocation(
        allocation.plan,
        candidates,
        inventory_batches,
        capacities,
        forecast,
        lanes=lanes,
        as_of=origin,
        sku_min_shelf_life_days=sku_min_shelf_life_days,
        config=cfg,
    )
    explanations = explain_allocation(
        allocation.plan,
        candidates,
        inventory_batches,
        capacities,
        forecast,
        transport_costs,
    )
    benchmark = run_benchmark(
        candidates,
        inventory_batches,
        forecast,
        held_out_actuals,
        capacities=capacities,
        transport_costs=transport_costs,
        config=cfg,
        as_of=origin,
    )
    return DemoResult(
        training=training,
        forecast=forecast,
        allocation=allocation,
        verification=verification,
        explanations=explanations,
        benchmark=benchmark,
    )


def synthetic_demo_inputs(
    *, start_date: date = date(2024, 1, 1)
) -> dict[str, object]:
    """Build deterministic synthetic inputs; these are not business data."""
    history_days = 84
    origin = start_date + timedelta(days=history_days - 1)
    sku_id = "demo-sku"
    destination_id = "demo-destination"
    warehouse_id = "demo-warehouse"
    demand = pd.DataFrame(
        [
            {
                "sku_id": sku_id,
                "destination_id": destination_id,
                "demand_date": start_date + timedelta(days=day),
                "quantity": float(12 + day % 7),
            }
            for day in range(history_days)
        ]
    )
    inventory = pd.DataFrame(
        [
            {
                "batch_id": "demo-batch",
                "sku_id": sku_id,
                "warehouse_id": warehouse_id,
                "quantity": 200.0,
                "expiry_date": origin + timedelta(days=120),
            }
        ]
    )
    lanes = pd.DataFrame(
        [
            {
                "warehouse_id": warehouse_id,
                "destination_id": destination_id,
                "is_available": True,
                "transit_days": 2,
            }
        ]
    )
    capacities = pd.DataFrame(
        [{"destination_id": destination_id, "capacity_units": 200.0}]
    )
    costs = pd.DataFrame(
        [
            {
                "warehouse_id": warehouse_id,
                "destination_id": destination_id,
                "unit_transport_cost": 2.5,
            }
        ]
    )
    held_out_actuals = pd.DataFrame(
        [
            {
                "sku_id": sku_id,
                "destination_id": destination_id,
                "demand_date": origin + timedelta(days=day),
                "quantity": float(12 + (history_days + day - 1) % 7),
            }
            for day in range(1, 8)
        ]
    )
    return {
        "demand_history": demand,
        "inventory_batches": inventory,
        "lanes": lanes,
        "sku_min_shelf_life_days": {sku_id: 7},
        "capacities": capacities,
        "transport_costs": costs,
        "held_out_actuals": held_out_actuals,
    }


def run_synthetic_demo(*, config: EngineConfig | None = None) -> DemoResult:
    """Run the full workflow against deterministic, explicitly synthetic data."""
    return run_demo_workflow(**synthetic_demo_inputs(), config=config)
