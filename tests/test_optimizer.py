"""Solver-backed shared-stock allocation tests."""

from __future__ import annotations

import pandas as pd
import pulp
import pytest

from aiml.exceptions import ValidationError
from aiml.optimization.checker import verify_allocation
from aiml.optimization.eligibility import eligible_shipments
from aiml.optimization.optimizer import optimize_allocation


def _shared_inputs():
    inventory = pd.DataFrame(
        {
            "batch_id": ["b1"],
            "sku_id": ["s1"],
            "warehouse_id": ["w1"],
            "quantity": [10],
            "expiry_date": pd.to_datetime(["2024-03-01"]),
        }
    )
    lanes = pd.DataFrame(
        {
            "warehouse_id": ["w1", "w1"],
            "destination_id": ["d1", "d2"],
            "is_available": [True, True],
            "transit_days": [1, 1],
        }
    )
    eligible = eligible_shipments(
        inventory, lanes, {"s1": 2}, origin_date="2024-01-01"
    )
    forecast = pd.DataFrame(
        {
            "sku_id": ["s1", "s1"],
            "destination_id": ["d1", "d2"],
            "point_forecast": [8, 8],
        }
    )
    capacity = pd.DataFrame(
        {"destination_id": ["d1", "d2"], "capacity_units": [8, 6]}
    )
    costs = pd.DataFrame(
        {
            "warehouse_id": ["w1", "w1"],
            "destination_id": ["d1", "d2"],
            "unit_transport_cost": [1.0, 3.0],
        }
    )
    return inventory, lanes, eligible, forecast, capacity, costs


def test_optimizer_allocates_jointly_with_shared_stock_and_costs() -> None:
    inventory, lanes, eligible, forecast, capacity, costs = _shared_inputs()
    result = optimize_allocation(
        eligible,
        inventory,
        capacity,
        forecast,
        costs,
        as_of="2024-01-01",
    )
    assert result.status == "optimal"
    assert result.plan["allocated_quantity"].sum() == pytest.approx(10)
    by_destination = result.plan.groupby("destination_id")["allocated_quantity"].sum()
    assert by_destination.to_dict() == pytest.approx({"d1": 8, "d2": 2})
    checked = verify_allocation(
        result.plan,
        eligible,
        inventory,
        capacity,
        forecast,
        lanes=lanes,
        as_of="2024-01-01",
        sku_min_shelf_life_days={"s1": 2},
    )
    assert checked.is_valid
    assert result.objective_value == pytest.approx(14.0)
    assert result.diagnostics["fefo_applied"] is True


def test_zero_demand_and_empty_candidates_are_safe() -> None:
    inventory, _, eligible, forecast, capacity, costs = _shared_inputs()
    forecast["point_forecast"] = 0
    result = optimize_allocation(eligible, inventory, capacity, forecast, costs)
    assert result.status == "optimal"
    assert result.plan.empty
    empty = eligible.iloc[0:0]
    empty_result = optimize_allocation(empty, inventory)
    assert empty_result.status == "optimal"
    assert empty_result.plan.empty


def test_missing_cost_for_candidate_is_rejected() -> None:
    inventory, _, eligible, forecast, capacity, costs = _shared_inputs()
    with pytest.raises(ValidationError, match="Missing transport cost"):
        optimize_allocation(
            eligible,
            inventory,
            capacity,
            forecast,
            costs.iloc[[0]].copy(),
        )


def test_solver_unavailable_is_returned_as_explicit_status() -> None:
    inventory, _, eligible, forecast, capacity, costs = _shared_inputs()

    class UnavailableSolver:
        def available(self):
            return None

    result = optimize_allocation(
        eligible,
        inventory,
        capacity,
        forecast,
        costs,
        solver=UnavailableSolver(),
    )
    assert result.status == "solver_unavailable"
    assert result.plan.empty
    assert result.objective_value is None


def test_effective_capacity_uses_latest_warehouse_specific_record() -> None:
    inventory = pd.DataFrame(
        {
            "batch_id": ["b1", "b2"],
            "sku_id": ["s1", "s1"],
            "warehouse_id": ["w1", "w2"],
            "quantity": [10, 10],
            "expiry_date": pd.to_datetime(["2024-12-01", "2024-12-01"]),
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
        inventory, lanes, {"s1": 0}, origin_date="2024-01-01"
    )
    capacities = pd.DataFrame(
        {
            "destination_id": ["d1", "d1", "d1"],
            "warehouse_id": ["w1", "w1", "w2"],
            "effective_date": pd.to_datetime(
                ["2024-01-01", "2024-01-10", "2024-01-10"]
            ),
            "capacity_units": [2, 3, 4],
        }
    )
    forecast = pd.DataFrame(
        {"sku_id": ["s1"], "destination_id": ["d1"], "point_forecast": [10]}
    )
    result = optimize_allocation(
        eligible,
        inventory,
        capacities,
        forecast,
        as_of="2024-01-15",
    )
    assert result.status == "optimal"
    allocated = result.plan.groupby("warehouse_id")["allocated_quantity"].sum()
    assert allocated.to_dict() == pytest.approx({"w1": 3, "w2": 4})
    assert result.plan["allocated_quantity"].sum() == pytest.approx(7)


def test_infeasible_solver_status_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, _, eligible, forecast, capacity, costs = _shared_inputs()

    class AvailableSolver:
        def available(self):
            return True

    def report_infeasible(_problem, _solver):
        return type(
            "SolveResult",
            (),
            {"status": pulp.LpSolveStatus.Infeasible, "has_solution": False},
        )()

    monkeypatch.setattr(pulp.LpProblem, "solve", report_infeasible)
    result = optimize_allocation(
        eligible,
        inventory,
        capacity,
        forecast,
        costs,
        solver=AvailableSolver(),
    )
    assert result.status == "infeasible"
    assert result.plan.empty
    assert result.objective_value is None


def test_forecast_demand_uses_only_selected_origin_and_horizon() -> None:
    inventory, _, eligible, _, capacity, _ = _shared_inputs()
    eligible = eligible.loc[eligible["destination_id"] == "d1"].copy()
    forecast = pd.DataFrame(
        {
            "sku_id": ["s1", "s1"],
            "destination_id": ["d1", "d1"],
            "forecast_origin": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "forecast_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "horizon_day": [1, 1],
            "point_forecast": [1, 100],
            "forecast_status": ["ok", "ok"],
            "model_name": ["test", "test"],
        }
    )
    result = optimize_allocation(
        eligible,
        inventory,
        capacity,
        forecast,
        as_of="2024-01-01",
    )
    assert result.status == "optimal"
    assert result.plan["allocated_quantity"].sum() == pytest.approx(1)
