"""Solve a lexicographic, shared-inventory shipment allocation model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
import pulp

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from .constraints import add_constraints
from .objective import build_objective


@dataclass
class AllocationResult:
    """Results and diagnostics from one optimization run."""

    plan: pd.DataFrame
    status: str
    objective_value: float | None
    solver_status_code: int | None
    constraints_added: int
    diagnostics: dict[str, Any] = field(default_factory=dict)


def optimize_allocation(
    eligible: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    capacities: pd.DataFrame | None = None,
    demand_forecast: pd.DataFrame | None = None,
    transport_costs: pd.DataFrame | None = None,
    *,
    config: EngineConfig | None = None,
    solver: Any | None = None,
    time_limit_seconds: int = 60,
    as_of: str | date | pd.Timestamp | None = None,
) -> AllocationResult:
    """Maximize demand served, then minimize freight, then apply FEFO.

    The stages are lexicographic; no arbitrary reward coefficient trades
    service against currency cost. Expiry-date tie-breaking is applied when
    expiry evidence is present. Holding and expiry-loss costs are not modeled
    because the input contract supplies no such cost parameters.
    """
    if not isinstance(eligible, pd.DataFrame):
        raise TypeError("eligible must be a pandas DataFrame.")
    if not isinstance(inventory_batches, pd.DataFrame):
        raise TypeError("inventory_batches must be a pandas DataFrame.")
    if not eligible.index.is_unique:
        raise ValidationError("Eligible shipment index must be unique.")
    if (
        isinstance(time_limit_seconds, bool)
        or not isinstance(time_limit_seconds, int)
        or time_limit_seconds <= 0
    ):
        raise ValidationError("time_limit_seconds must be a positive integer.")

    cfg = config or EngineConfig()
    cols = cfg.columns
    required = {
        cols.batch_id,
        cols.sku_id,
        cols.warehouse_id,
        cols.destination_id,
        cols.quantity,
    }
    missing = required - set(eligible.columns)
    if missing:
        raise SchemaError(
            "Eligible shipments are missing required columns.",
            details={"missing_columns": sorted(missing)},
        )

    plan_columns = list(eligible.columns) + ["allocated_quantity", "eligible_row_id"]
    if eligible.empty:
        return AllocationResult(
            plan=pd.DataFrame(columns=plan_columns),
            status="optimal",
            objective_value=0.0,
            solver_status_code=None,
            constraints_added=0,
            diagnostics={"message": "No eligible shipment candidates.", "total_allocated": 0.0},
        )

    problem = pulp.LpProblem("Optiqo_Allocation", pulp.LpMaximize)
    decision_vars: dict[Any, pulp.LpVariable] = {}
    for position, (row_id, row) in enumerate(eligible.iterrows()):
        value = pd.to_numeric(pd.Series([row[cols.quantity]]), errors="coerce").iloc[0]
        if pd.isna(value) or not pd.api.types.is_number(value) or not pd.notna(value) or abs(float(value)) == float("inf") or value < 0:
            raise ValidationError(
                "Candidate quantity must be finite and non-negative.",
                details={"row_id": repr(row_id)},
            )
        decision_vars[row_id] = problem.add_variable(
            f"ship_{position}", lowBound=0, upBound=float(value)
        )

    constraints = add_constraints(
        problem,
        decision_vars,
        eligible,
        inventory_batches,
        capacities,
        demand_forecast,
        config=cfg,
        as_of=as_of,
    )
    service_expression = pulp.lpSum(decision_vars.values())
    active_solver = solver or pulp.getSolver(
        "COIN_CMD", msg=False, timeLimit=time_limit_seconds
    )

    if not active_solver.available():
        return AllocationResult(
            plan=pd.DataFrame(columns=plan_columns),
            status="solver_unavailable",
            objective_value=None,
            solver_status_code=None,
            constraints_added=len(constraints),
            diagnostics={"solver_name": type(active_solver).__name__, "solver_available": False},
        )

    def solve_stage(stage: str) -> tuple[str, int | None, str | None]:
        try:
            solve_result = problem.solve(active_solver)
        except (pulp.PulpSolverError, OSError) as exc:
            return "solver_failure", None, f"{stage}: {exc}"
        if hasattr(solve_result, "status"):
            status_value = solve_result.status
            label = getattr(status_value, "name", str(status_value))
            code = int(status_value)
            has_solution = bool(getattr(solve_result, "has_solution", False))
        else:
            code = int(solve_result)
            label = getattr(pulp, "LpStatus", {}).get(code, str(code))
            solution_label = getattr(pulp, "LpSolution", {}).get(
                getattr(problem, "sol_status", None), "Unknown"
            )
            has_solution = solution_label == "Integer Feasible"
        if label == "Optimal":
            return "optimal", code, None
        if has_solution:
            return "feasible", code, f"{stage}: solver stopped with a feasible incumbent ({label})"
        if label == "Infeasible":
            return "infeasible", code, None
        return "solver_failure", code, f"{stage}: solver status was {label}"

    def current_plan() -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for row_id, row in eligible.iterrows():
            value = pulp.value(decision_vars[row_id])
            if value is None:
                continue
            shipped = float(value)
            if abs(shipped) < 1e-8:
                continue
            item = row.to_dict()
            item["allocated_quantity"] = shipped
            item["eligible_row_id"] = row_id
            rows.append(item)
        return pd.DataFrame(rows, columns=plan_columns)

    problem.objective = service_expression
    problem.sense = pulp.LpMaximize
    service_status, status_code, error = solve_stage("service")
    if service_status != "optimal":
        plan = current_plan() if service_status == "feasible" else pd.DataFrame(columns=plan_columns)
        return AllocationResult(
            plan=plan,
            status=service_status,
            objective_value=None,
            solver_status_code=status_code,
            constraints_added=len(constraints),
            diagnostics={
                "solver_name": type(active_solver).__name__,
                "message": error,
                "service_stage_complete": service_status == "optimal",
            },
        )

    max_service = float(pulp.value(service_expression) or 0.0)
    service_constraint = service_expression == max_service
    problem += service_constraint, "lexicographic_service"
    constraints.append(service_constraint)

    build_objective(
        problem, decision_vars, eligible, transport_costs, config=cfg
    )
    freight_status, freight_code, freight_error = solve_stage("freight")
    if freight_status != "optimal":
        return AllocationResult(
            plan=current_plan() if freight_status == "feasible" else pd.DataFrame(columns=plan_columns),
            status=freight_status,
            objective_value=None,
            solver_status_code=freight_code,
            constraints_added=len(constraints),
            diagnostics={
                "solver_name": type(active_solver).__name__,
                "message": freight_error,
                "service_optimum": max_service,
                "service_stage_complete": True,
                "freight_stage_complete": False,
            },
        )

    status_code = freight_code
    freight_value = float(pulp.value(problem.objective) or 0.0)
    diagnostics: dict[str, Any] = {
        "solver_name": type(active_solver).__name__,
        "solver_available": True,
        "total_allocated": float(sum(float(pulp.value(v) or 0.0) for v in decision_vars.values())),
        "service_optimum": max_service,
        "freight_cost": freight_value,
        "freight_stage_complete": True,
        "fefo_applied": False,
    }

    expiry_column = cols.expiry_date
    life_column = "remaining_shelf_life_days_at_arrival"
    if expiry_column in eligible.columns or life_column in eligible.columns:
        freight_constraint = problem.objective == freight_value
        problem += freight_constraint, "lexicographic_freight"
        constraints.append(freight_constraint)
        if expiry_column in eligible.columns:
            expiry = pd.to_datetime(eligible[expiry_column], errors="coerce")
            if expiry.isna().any():
                raise ValidationError("FEFO requires finite expiry dates for all eligible candidates.")
            score = (expiry - expiry.min()).dt.days.astype(float)
        else:
            life = pd.to_numeric(eligible[life_column], errors="coerce")
            if life.isna().any() or not life.map(lambda item: pd.notna(item) and abs(float(item)) != float("inf")).all():
                raise ValidationError("FEFO requires finite remaining-shelf-life values.")
            score = life.astype(float)
        fefo_objective = pulp.lpSum(
            float(score.loc[row_id]) * decision_vars[row_id]
            for row_id in eligible.index
        )
        problem.objective = fefo_objective
        problem.sense = pulp.LpMinimize
        fefo_status, fefo_code, fefo_error = solve_stage("fefo")
        if fefo_status != "optimal":
            return AllocationResult(
                plan=current_plan() if fefo_status == "feasible" else pd.DataFrame(columns=plan_columns),
                status=fefo_status,
                objective_value=freight_value,
                solver_status_code=fefo_code,
                constraints_added=len(constraints),
                diagnostics={
                    **diagnostics,
                    "message": fefo_error,
                    "fefo_stage_complete": False,
                },
            )
        status_code = fefo_code
        diagnostics["fefo_applied"] = True

    final_plan = current_plan()
    diagnostics["allocated_lines"] = len(final_plan)
    return AllocationResult(
        plan=final_plan,
        status="optimal",
        objective_value=freight_value,
        solver_status_code=status_code,
        constraints_added=len(constraints),
        diagnostics=diagnostics,
    )
