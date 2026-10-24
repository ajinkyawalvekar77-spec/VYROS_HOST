"""Explicit adapters from JSON records to the existing Optiqo engine."""

from __future__ import annotations

import importlib
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .config import get_settings


class EngineUnavailableError(RuntimeError):
    """Raised when the configured engine package cannot be loaded."""


@dataclass
class ForecastRun:
    frame: pd.DataFrame
    response: dict[str, Any]
    config: Any


@lru_cache(maxsize=1)
def _load_engine() -> dict[str, Any]:
    engine_path = get_settings().engine_path
    if not (engine_path / "__init__.py").is_file():
        raise EngineUnavailableError(
            f"Optiqo engine package was not found at {engine_path}."
        )
    engine_parent = str(engine_path.parent)
    if engine_parent in sys.path:
        sys.path.remove(engine_parent)
    sys.path.insert(0, engine_parent)
    loaded_package = sys.modules.get("aiml")
    loaded_location = getattr(loaded_package, "__file__", None)
    if loaded_location and Path(loaded_location).resolve().parent != engine_path:
        raise EngineUnavailableError(
            "A different `aiml` package is already loaded in this process; "
            f"expected the configured engine at {engine_path}, got {loaded_location}."
        )
    try:
        config_module = importlib.import_module("aiml.config")
        schemas_module = importlib.import_module("aiml.schemas")
        training_module = importlib.import_module("aiml.forecasting.training")
        prediction_module = importlib.import_module("aiml.forecasting.prediction")
        eligibility_module = importlib.import_module("aiml.optimization.eligibility")
        optimizer_module = importlib.import_module("aiml.optimization.optimizer")
        checker_module = importlib.import_module("aiml.optimization.checker")
        explanation_module = importlib.import_module("aiml.optimization.explanations")
        benchmark_module = importlib.import_module("aiml.evaluation.benchmark")
    except (ImportError, OSError) as exc:
        raise EngineUnavailableError(
            f"Optiqo engine imports failed: {type(exc).__name__}: {exc}"
        ) from exc
    return {
        "EngineConfig": config_module.EngineConfig,
        "ForecastConfig": config_module.ForecastConfig,
        "validate_demand": schemas_module.validate_demand,
        "validate_inventory_batches": schemas_module.validate_inventory_batches,
        "validate_lanes": schemas_module.validate_lanes,
        "validate_transport_costs": schemas_module.validate_transport_costs,
        "validate_capacities": schemas_module.validate_capacities,
        "select_and_train": training_module.select_and_train,
        "forecast_seven_day": prediction_module.forecast_seven_day,
        "eligible_shipments": eligibility_module.eligible_shipments,
        "optimize_allocation": optimizer_module.optimize_allocation,
        "verify_allocation": checker_module.verify_allocation,
        "explain_allocation": explanation_module.explain_allocation,
        "run_benchmark": benchmark_module.run_benchmark,
    }


def engine_readiness() -> tuple[bool, str | None]:
    try:
        _load_engine()
    except EngineUnavailableError as exc:
        return False, str(exc)
    return True, None


def frame_from_rows(rows: list[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(rows)


def json_safe(value: Any) -> Any:
    """Convert NumPy, pandas, and date values into strict JSON-native values."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return [json_safe(record) for record in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return [json_safe(item) for item in value.tolist()]
    return value


def run_forecast(
    demand_rows: list[Mapping[str, Any]],
    *,
    origin: date | str | None = None,
    horizon_days: int = 7,
) -> ForecastRun:
    engine = _load_engine()
    config = engine["EngineConfig"](
        forecast=engine["ForecastConfig"](horizon_days=horizon_days)
    )
    demand = frame_from_rows(demand_rows)
    validated = engine["validate_demand"](demand, config=config).frame
    date_column = config.columns.demand_date
    latest_history_date = pd.to_datetime(validated[date_column]).max().normalize()
    used_origin = (
        pd.Timestamp(origin).normalize() if origin is not None else latest_history_date
    )
    observed = validated.loc[validated[date_column] <= used_origin].copy()
    if observed.empty:
        raise ValueError("No demand history exists on or before the requested origin.")
    ignored_rows = len(validated) - len(observed)
    training = engine["select_and_train"](observed, config=config)
    forecast = engine["forecast_seven_day"](
        observed,
        training,
        origin=used_origin,
        config=config,
    )
    response = {
        "model_name": training.model_name,
        "fallback_used": training.fallback_reason is not None,
        "fallback_reason": training.fallback_reason,
        "origin": used_origin.date(),
        "horizon_days": horizon_days,
        "history_rows_used": len(observed),
        "history_rows_after_origin_ignored": ignored_rows,
        "validation_metrics": training.validation_metrics,
        "model_validation_metrics": training.model_validation_metrics,
        "forecasts": json_safe(forecast),
    }
    return ForecastRun(forecast, json_safe(response), config)


def run_plan(
    *,
    demand_history: list[Mapping[str, Any]],
    inventory_batches: list[Mapping[str, Any]],
    lanes: list[Mapping[str, Any]],
    transport_costs: list[Mapping[str, Any]],
    capacities: list[Mapping[str, Any]],
    sku_min_shelf_life_days: Mapping[str, int],
    held_out_actuals: list[Mapping[str, Any]] | None = None,
    origin: date | str | None = None,
    horizon_days: int = 7,
    solver_time_limit_seconds: int = 60,
) -> dict[str, Any]:
    engine = _load_engine()
    forecast_run = run_forecast(
        demand_history, origin=origin, horizon_days=horizon_days
    )
    config = forecast_run.config
    inventory = frame_from_rows(inventory_batches)
    lane_frame = frame_from_rows(lanes)
    cost_frame = frame_from_rows(transport_costs)
    capacity_frame = frame_from_rows(capacities)
    origin_date = forecast_run.response["origin"]

    engine["validate_inventory_batches"](inventory, config=config)
    engine["validate_lanes"](lane_frame, config=config)
    engine["validate_transport_costs"](cost_frame, config=config)
    if not capacity_frame.empty:
        engine["validate_capacities"](capacity_frame, config=config)

    candidates = engine["eligible_shipments"](
        inventory,
        lane_frame,
        sku_min_shelf_life_days,
        origin_date=origin_date,
        config=config,
    )
    allocation = engine["optimize_allocation"](
        candidates,
        inventory,
        capacity_frame if not capacity_frame.empty else None,
        forecast_run.frame,
        cost_frame,
        config=config,
        time_limit_seconds=solver_time_limit_seconds,
        as_of=origin_date,
    )
    if allocation.status in {"optimal", "feasible"}:
        verification = engine["verify_allocation"](
            allocation.plan,
            candidates,
            inventory,
            capacity_frame if not capacity_frame.empty else None,
            forecast_run.frame,
            lanes=lane_frame,
            as_of=origin_date,
            sku_min_shelf_life_days=sku_min_shelf_life_days,
            config=config,
        )
        verification_result: dict[str, Any] = {
            "is_valid": verification.is_valid,
            "checks_passed": verification.checks_passed,
            "checks_failed": verification.checks_failed,
            "checks_not_run": verification.checks_not_run,
            "violations": verification.to_frame(),
            "summary": verification.summary,
        }
        explanations = engine["explain_allocation"](
            allocation.plan,
            candidates,
            inventory,
            capacity_frame if not capacity_frame.empty else None,
            forecast_run.frame,
            cost_frame,
        )
    else:
        verification_result = {
            "is_valid": False,
            "checks_passed": 0,
            "checks_failed": 0,
            "checks_not_run": [
                f"No verified plan is available for solver status {allocation.status}."
            ],
            "violations": [],
            "summary": "No plan was produced; verification was not run.",
        }
        explanations = pd.DataFrame()

    benchmark = None
    if held_out_actuals is not None and allocation.status in {"optimal", "feasible"}:
        benchmark_result = engine["run_benchmark"](
            candidates,
            inventory,
            forecast_run.frame,
            frame_from_rows(held_out_actuals),
            capacities=capacity_frame if not capacity_frame.empty else None,
            transport_costs=cost_frame,
            config=config,
            as_of=origin_date,
            time_limit_seconds=solver_time_limit_seconds,
        )
        benchmark = {
            "optimizer_status": benchmark_result.optimizer_status,
            "metrics": json_safe(benchmark_result.metrics),
            "assumptions": list(benchmark_result.assumptions),
        }

    return json_safe(
        {
            "forecast": forecast_run.response,
            "solver": {
                "status": allocation.status,
                "objective_value": allocation.objective_value,
                "solver_status_code": allocation.solver_status_code,
                "constraints_added": allocation.constraints_added,
                "diagnostics": allocation.diagnostics,
            },
            "plan": allocation.plan,
            "verification": verification_result,
            "explanations": explanations,
            "benchmark": benchmark,
            "objective_note": (
                "The engine maximizes demand served, then minimizes freight, then applies "
                "FEFO tie-breaking. Monetary unmet-demand, expiry-loss, and holding "
                "penalties are not configured; shipment quantities are continuous."
            ),
        }
    )
