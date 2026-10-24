"""Reproducible comparison of optimized and deterministic allocation policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from ..optimization.optimizer import AllocationResult, optimize_allocation
from ..schemas import validate_capacities, validate_demand, validate_inventory_batches, validate_transport_costs
from .allocation_metrics import allocation_metrics


@dataclass
class BenchmarkResult:
    """Policy metrics and the corresponding shipment plans."""

    metrics: pd.DataFrame
    plans: dict[str, pd.DataFrame]
    optimizer_status: str
    assumptions: tuple[str, ...]


def _pair_demand(
    forecast: pd.DataFrame,
    *,
    sku_col: str,
    destination_col: str,
    quantity_col: str,
    status_col: str,
    origin_col: str,
    forecast_date_col: str,
    as_of: str | date | pd.Timestamp,
    horizon_days: int,
) -> dict[tuple[str, str], float]:
    required = {sku_col, destination_col, quantity_col}
    if missing := required - set(forecast.columns):
        raise SchemaError("Forecast is missing required columns.", details={"missing_columns": sorted(missing)})
    usable = forecast.copy()
    origin = pd.Timestamp(as_of).normalize()
    if origin_col in usable.columns:
        origins = pd.to_datetime(usable[origin_col], errors="coerce").dt.normalize()
        if origins.isna().any():
            raise ValidationError("Forecast origins must contain valid dates.")
        usable = usable.loc[origins == origin].copy()
    if forecast_date_col in usable.columns:
        forecast_dates = pd.to_datetime(
            usable[forecast_date_col], errors="coerce"
        ).dt.normalize()
        if forecast_dates.isna().any():
            raise ValidationError("Forecast dates must contain valid dates.")
        usable = usable.loc[
            (forecast_dates > origin)
            & (forecast_dates <= origin + pd.Timedelta(days=horizon_days))
        ].copy()
    if status_col in usable.columns:
        usable = usable.loc[usable[status_col] == "ok"].copy()
    usable[quantity_col] = pd.to_numeric(usable[quantity_col], errors="coerce")
    if (
        usable[quantity_col].isna().any()
        or (~usable[quantity_col].map(lambda value: pd.notna(value) and abs(float(value)) != float("inf"))).any()
        or (usable[quantity_col] < 0).any()
    ):
        raise ValidationError("Forecast values must be finite and non-negative.")
    usable[sku_col] = usable[sku_col].astype(str)
    usable[destination_col] = usable[destination_col].astype(str)
    grouped = usable.groupby([sku_col, destination_col])[quantity_col].sum()
    return {
        (str(sku), str(destination)): float(quantity)
        for (sku, destination), quantity in grouped.items()
    }


def _greedy_plan(
    policy: str,
    eligible: pd.DataFrame,
    inventory: pd.DataFrame,
    forecast: pd.DataFrame,
    capacities: pd.DataFrame | None,
    costs: pd.DataFrame | None,
    *,
    config: EngineConfig,
    as_of: str | date | pd.Timestamp | None,
) -> pd.DataFrame:
    cols = config.columns
    pair_demand = _pair_demand(
        forecast,
        sku_col=cols.sku_id,
        destination_col=cols.destination_id,
        quantity_col=cols.point_forecast,
        status_col=cols.forecast_status,
        origin_col=cols.forecast_origin,
        forecast_date_col=cols.forecast_date,
        as_of=as_of,
        horizon_days=config.forecast.horizon_days,
    )
    stock_left = inventory.set_index(cols.batch_id)[cols.quantity].astype(float).to_dict()
    demand_left = dict(pair_demand)

    capacity_left: dict[tuple[str, ...], float] = {}
    capacity_dims: list[str] = []
    if capacities is not None:
        cap = capacities.copy()
        capacity_dims = [cols.destination_id]
        capacity_dims.extend(key for key in (cols.sku_id, cols.warehouse_id) if key in cap.columns)
        if cols.effective_date in cap.columns:
            if as_of is None:
                raise ValidationError("Benchmarking effective-dated capacity requires as_of.")
            cap[cols.effective_date] = pd.to_datetime(cap[cols.effective_date]).dt.normalize()
            cap = cap.loc[cap[cols.effective_date] <= pd.Timestamp(as_of).normalize()].copy()
            if cap.empty:
                raise ValidationError("No capacity record is effective on or before as_of.")
            latest = cap.groupby(capacity_dims)[cols.effective_date].transform("max")
            cap = cap.loc[cap[cols.effective_date] == latest]
        if cap.duplicated(capacity_dims).any():
            raise ValidationError(f"Capacity is ambiguous at dimensions {capacity_dims}.")
        capacity_left = {
            tuple(str(row[key]) for key in capacity_dims): float(row[cols.capacity_units])
            for row in cap.to_dict("records")
        }

    unit_cost: dict[tuple[str, ...], float] = {}
    if costs is not None:
        sku_cost = cols.sku_id in costs.columns
        cost_dims = [cols.warehouse_id, cols.destination_id]
        if sku_cost:
            cost_dims.insert(0, cols.sku_id)
        unit_cost = {
            tuple(str(row[key]) for key in cost_dims): float(row[cols.unit_transport_cost])
            for row in costs.to_dict("records")
        }
    else:
        cost_dims = [cols.warehouse_id, cols.destination_id]

    rows = eligible.copy()
    rows["_expiry_order"] = pd.to_datetime(rows[cols.expiry_date], errors="coerce") if cols.expiry_date in rows.columns else pd.NaT
    rows["_cost_order"] = [
        unit_cost.get(tuple(str(row[key]) for key in cost_dims), 0.0)
        for _, row in rows.iterrows()
    ]
    if costs is not None and any(
        tuple(str(row[key]) for key in cost_dims) not in unit_cost for _, row in rows.iterrows()
    ):
        raise ValidationError("A benchmark candidate has no matching transport cost.")
    if policy == "cheapest_first":
        rows = rows.sort_values(["_cost_order", "_expiry_order"], na_position="last", kind="stable")
    elif policy == "fefo_first":
        rows = rows.sort_values(["_expiry_order", "_cost_order"], na_position="last", kind="stable")
    else:
        raise ValueError(f"Unknown greedy policy: {policy}")

    allocations: list[dict[str, Any]] = []
    for row_id, row in rows.iterrows():
        batch_id = str(row[cols.batch_id])
        pair = (str(row[cols.sku_id]), str(row[cols.destination_id]))
        key = tuple(str(row[column]) for column in capacity_dims)
        candidate_limit = float(row[cols.quantity])
        quantity = min(candidate_limit, stock_left.get(batch_id, 0.0), demand_left.get(pair, 0.0))
        if capacities is not None:
            if key not in capacity_left:
                raise ValidationError("No applicable capacity record exists for a benchmark candidate.", details={"capacity_key": key})
            quantity = min(quantity, capacity_left[key])
            capacity_left[key] -= quantity
        stock_left[batch_id] = stock_left.get(batch_id, 0.0) - quantity
        demand_left[pair] = demand_left.get(pair, 0.0) - quantity
        if quantity > 1e-9:
            item = row.drop(labels=["_expiry_order", "_cost_order"]).to_dict()
            item["allocated_quantity"] = quantity
            item["eligible_row_id"] = row_id
            allocations.append(item)
    columns = list(eligible.columns) + ["allocated_quantity", "eligible_row_id"]
    return pd.DataFrame(allocations, columns=columns)


def run_benchmark(
    eligible: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    demand_forecast: pd.DataFrame,
    actual_demand: pd.DataFrame,
    *,
    capacities: pd.DataFrame | None = None,
    transport_costs: pd.DataFrame | None = None,
    as_of: str | date | pd.Timestamp | None = None,
    config: EngineConfig | None = None,
    solver: Any | None = None,
    time_limit_seconds: int = 60,
) -> BenchmarkResult:
    """Compare optimizer, cheapest-first, and FEFO-first on identical inputs.

    The supplied actual demand must be held-out chronological data. This
    function does not split data or claim forecast lift; it reports allocation
    outcomes against the caller's held-out actuals and forecast-based limits.
    """
    cfg = config or EngineConfig()
    cols = cfg.columns
    if as_of is None:
        raise ValidationError("Benchmark evaluation requires an as_of origin date.")
    origin = pd.Timestamp(as_of).normalize()
    held_out = validate_demand(actual_demand, config=cfg).frame
    end = origin + pd.Timedelta(days=cfg.forecast.horizon_days)
    outside = (held_out[cols.demand_date] <= origin) | (held_out[cols.demand_date] > end)
    if outside.any():
        raise ValidationError(
            "Benchmark actual demand must be held out after as_of and within the configured horizon.",
            details={"invalid_rows": int(outside.sum()), "as_of": str(origin.date()), "horizon_end": str(end.date())},
        )
    inventory_batches = validate_inventory_batches(inventory_batches, config=cfg).frame
    if capacities is not None:
        capacities = validate_capacities(capacities, config=cfg).frame
    if transport_costs is not None:
        transport_costs = validate_transport_costs(transport_costs, config=cfg).frame
    result: AllocationResult = optimize_allocation(
        eligible,
        inventory_batches,
        capacities,
        demand_forecast,
        transport_costs,
        config=cfg,
        solver=solver,
        time_limit_seconds=time_limit_seconds,
        as_of=as_of,
    )
    plans = {
        "optiqo": result.plan,
        "cheapest_first": _greedy_plan(
            "cheapest_first", eligible, inventory_batches, demand_forecast,
            capacities, transport_costs, config=cfg, as_of=as_of,
        ),
        "fefo_first": _greedy_plan(
            "fefo_first", eligible, inventory_batches, demand_forecast,
            capacities, transport_costs, config=cfg, as_of=as_of,
        ),
    }
    records = []
    for policy, plan in plans.items():
        metrics = allocation_metrics(
            plan,
            held_out,
            inventory_batches,
            transport_costs,
            as_of=as_of,
            horizon_days=cfg.forecast.horizon_days,
            config=cfg,
        )
        records.append({"policy": policy, "status": result.status if policy == "optiqo" else "evaluated", **metrics})
    return BenchmarkResult(
        metrics=pd.DataFrame(records),
        plans=plans,
        optimizer_status=result.status,
        assumptions=(
            "Actual demand is held out and used only for evaluation.",
            "All policies use the same eligible candidates, forecast demand ceiling, capacity, inventory, and transport costs.",
            "Greedy baselines process candidates sequentially; they are not claimed to be globally optimal.",
            "Freight is the only modeled monetary cost; unmet-demand, expiry-loss, and holding-cost penalties are excluded.",
        ),
    )
