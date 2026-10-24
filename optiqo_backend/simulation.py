"""Chronological backtest orchestration around the existing Optiqo engine."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .engine_adapter import _load_engine, frame_from_rows, json_safe, run_forecast


POLICY_NAMES = ("optiqo", "cheapest_first", "fefo_first")


def _date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _expiry(value: Any) -> date:
    return date.max if value is None or pd.isna(value) else _date(value)


def _eligible_inventory(
    rows: list[dict[str, Any]], receipts: list[dict[str, Any]], through: date
) -> list[dict[str, Any]]:
    result = [dict(row) for row in rows]
    result.extend(
        {
            "batch_id": row["batch_id"],
            "sku_id": row["sku_id"],
            "warehouse_id": row["warehouse_id"],
            "quantity": row["quantity"],
            "expiry_date": row["expiry_date"],
            "received_date": row["arrival_date"],
        }
        for row in receipts
        if _date(row["arrival_date"]) <= through
    )
    return result


def _capacity_dimensions(frame: pd.DataFrame, columns: Any) -> list[str]:
    return [columns.destination_id] + [
        key for key in (columns.sku_id, columns.warehouse_id) if key in frame.columns
    ]


def _capacity_key(record: dict[str, Any], dimensions: list[str]) -> tuple[str, ...]:
    return tuple(str(record[key]) for key in dimensions)


def _forecast_after_existing_stock(
    forecast: pd.DataFrame,
    destination_lots: list[dict[str, Any]],
    pipeline: list[dict[str, Any]],
    config: Any,
) -> pd.DataFrame:
    cols = config.columns
    result = forecast.copy()
    point = cols.point_forecast
    result[point] = pd.to_numeric(result[point], errors="raise").clip(lower=0)
    pair_keys = [cols.sku_id, cols.destination_id]
    for pair, indices in result.groupby(pair_keys, sort=False).groups.items():
        sku_id, destination_id = map(str, pair)
        lots: list[dict[str, Any]] = []
        for lot in destination_lots:
            if (
                str(lot["sku_id"]) == sku_id
                and str(lot["destination_id"]) == destination_id
                and lot["quantity"] > 0
            ):
                lots.append(
                    {
                        "available": date.min,
                        "expiry": _expiry(lot.get("expiry_date")),
                        "quantity": float(lot["quantity"]),
                        "batch_id": str(lot["batch_id"]),
                    }
                )
        for shipment in pipeline:
            if (
                str(shipment["sku_id"]) == sku_id
                and str(shipment["destination_id"]) == destination_id
            ):
                lots.append(
                    {
                        "available": _date(shipment["arrival_date"]),
                        "expiry": _expiry(shipment.get("expiry_date")),
                        "quantity": float(shipment["quantity"]),
                        "batch_id": str(shipment["batch_id"]),
                    }
                )
        for index in sorted(indices, key=lambda item: _date(result.at[item, cols.forecast_date])):
            target_date = _date(result.at[index, cols.forecast_date])
            available = sorted(
                (
                    lot
                    for lot in lots
                    if lot["available"] <= target_date
                    and lot["expiry"] > target_date
                    and lot["quantity"] > 1e-9
                ),
                key=lambda lot: (lot["expiry"], lot["batch_id"]),
            )
            demand_to_cover = float(result.at[index, point])
            for lot in available:
                used = min(demand_to_cover, lot["quantity"])
                lot["quantity"] -= used
                demand_to_cover -= used
                if demand_to_cover <= 1e-9:
                    break
            deduction = float(result.at[index, point]) - demand_to_cover
            result.at[index, point] = max(
                0.0, float(result.at[index, point]) - deduction
            )
    return result


def _capacity_remaining(
    capacities: pd.DataFrame,
    destination_lots: list[dict[str, Any]],
    pipeline: list[dict[str, Any]],
    config: Any,
) -> pd.DataFrame:
    if capacities.empty:
        return capacities
    cols = config.columns
    result = capacities.copy()
    dimensions = _capacity_dimensions(result, cols)
    occupied: dict[tuple[str, ...], float] = defaultdict(float)
    for lot in destination_lots:
        row = {
            cols.destination_id: lot["destination_id"],
            cols.sku_id: lot["sku_id"],
            cols.warehouse_id: lot.get("warehouse_id", ""),
        }
        key = _capacity_key(row, dimensions)
        occupied[key] += float(lot["quantity"])
    for shipment in pipeline:
        key = _capacity_key(shipment, dimensions)
        occupied[key] += float(shipment["quantity"])
    for index, row in result.iterrows():
        key = _capacity_key(row.to_dict(), dimensions)
        result.at[index, cols.capacity_units] = max(
            0.0, float(row[cols.capacity_units]) - occupied.get(key, 0.0)
        )
    return result


def _make_dispatch_plans(
    *,
    policy: str,
    demand_history: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    destination_lots: list[dict[str, Any]],
    pipeline: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    costs: list[dict[str, Any]],
    capacities: list[dict[str, Any]],
    shelf_life: dict[str, int],
    actuals: list[dict[str, Any]],
    origin: date,
    solver_time_limit_seconds: int,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    engine = _load_engine()
    forecast_run = run_forecast(
        demand_history, origin=origin, horizon_days=7
    )
    config = forecast_run.config
    cols = config.columns
    stock_aware_forecast = _forecast_after_existing_stock(
        forecast_run.frame, destination_lots, pipeline, config
    )
    capacity_frame = _capacity_remaining(
        frame_from_rows(capacities), destination_lots, pipeline, config
    )
    inventory_frame = frame_from_rows(inventory)
    lane_frame = frame_from_rows(lanes)
    cost_frame = frame_from_rows(costs)
    if inventory_frame.empty:
        empty_plan = pd.DataFrame(
            columns=[
                cols.batch_id,
                cols.sku_id,
                cols.warehouse_id,
                cols.destination_id,
                "allocated_quantity",
            ]
        )
        cycle = {
            "policy": policy,
            "origin": origin.isoformat(),
            "forecast_model": forecast_run.response["model_name"],
            "forecast_fallback_used": forecast_run.response["fallback_used"],
            "optimizer_status": "no_usable_warehouse_stock",
            "verification": {
                "status": "no_usable_warehouse_stock",
                "is_valid": False if policy == "optiqo" else True,
                "checks_failed": 0,
                "violations": [],
            },
            "runtime_seconds": time.perf_counter() - started,
            "plan_lines": 0,
        }
        return empty_plan, json_safe(forecast_run.response), cycle
    engine["validate_inventory_batches"](inventory_frame, config=config)
    eligible = engine["eligible_shipments"](
        inventory_frame,
        lane_frame,
        shelf_life,
        origin_date=origin,
        config=config,
    )
    if not capacity_frame.empty:
        capacity_dims = _capacity_dimensions(capacity_frame, cols)
        blocked_capacity = {
            _capacity_key(row, capacity_dims)
            for row in capacity_frame.to_dict("records")
            if float(row[cols.capacity_units]) <= 0
        }
        if blocked_capacity:
            eligible = eligible.loc[
                ~eligible.apply(
                    lambda row: _capacity_key(row.to_dict(), capacity_dims)
                    in blocked_capacity,
                    axis=1,
                )
            ].copy()
            capacity_frame = capacity_frame.loc[
                capacity_frame[cols.capacity_units] > 0
            ].copy()
    benchmark = engine["run_benchmark"](
        eligible,
        inventory_frame,
        stock_aware_forecast,
        frame_from_rows(actuals),
        capacities=capacity_frame if not capacity_frame.empty else None,
        transport_costs=cost_frame,
        as_of=origin,
        config=config,
        time_limit_seconds=solver_time_limit_seconds,
    )
    plan = benchmark.plans[policy]
    can_verify_optimizer = benchmark.optimizer_status in {"optimal", "feasible"}
    if policy == "optiqo" and not can_verify_optimizer:
        verification: dict[str, Any] = {
            "status": benchmark.optimizer_status,
            "is_valid": False,
            "checks_failed": 1,
            "violations": [
                {
                    "check": "solver_status",
                    "message": "The engine produced no usable optimizer plan.",
                    "status": benchmark.optimizer_status,
                }
            ],
        }
        plan = pd.DataFrame(columns=list(eligible.columns) + ["allocated_quantity"])
    else:
        checked = engine["verify_allocation"](
            plan,
            eligible,
            inventory_frame,
            capacity_frame if not capacity_frame.empty else None,
            stock_aware_forecast,
            lanes=lane_frame,
            as_of=origin,
            sku_min_shelf_life_days=shelf_life,
            config=config,
        )
        verification = {
            "status": "verified" if checked.is_valid else "invalid",
            "is_valid": checked.is_valid,
            "checks_failed": checked.checks_failed,
            "violations": json_safe(checked.to_frame()),
        }
        if not checked.is_valid:
            plan = pd.DataFrame(columns=list(eligible.columns) + ["allocated_quantity"])
    cycle = {
        "policy": policy,
        "origin": origin.isoformat(),
        "forecast_model": forecast_run.response["model_name"],
        "forecast_fallback_used": forecast_run.response["fallback_used"],
        "optimizer_status": benchmark.optimizer_status,
        "verification": verification,
        "independent_verification": verification,
        "runtime_seconds": time.perf_counter() - started,
        "plan_lines": len(plan),
    }
    return plan, json_safe(forecast_run.response), cycle


def _new_state(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "warehouse": [
            {
                "batch_id": str(row["batch_id"]),
                "sku_id": str(row["sku_id"]),
                "warehouse_id": str(row["warehouse_id"]),
                "quantity": float(row["quantity"]),
                "expiry_date": _expiry(row.get("expiry_date")),
            }
            for row in inventory
        ],
        "destination": [],
        "pipeline": [],
        "freight_cost": 0.0,
        "shipped_units": 0.0,
        "expired_units": 0.0,
        "demand_units": 0.0,
        "fulfilled_units": 0.0,
        "unmet_units": 0.0,
        "positive_demand_pair_days": 0,
        "stockout_pair_days": 0,
        "supplied_units": sum(float(row["quantity"]) for row in inventory),
        "daily": [],
        "network_daily": [],
        "inventory_balances": [],
        "simulator_violations": [],
    }


def _metric_row(
    policy: str, state: dict[str, Any], elapsed: float
) -> dict[str, Any]:
    demand = state["demand_units"]
    fulfilled = state["fulfilled_units"]
    ending_warehouse = sum(row["quantity"] for row in state["warehouse"])
    ending_destination = sum(row["quantity"] for row in state["destination"])
    ending_in_transit = sum(row["quantity"] for row in state["pipeline"])
    denominator = state["positive_demand_pair_days"]
    return {
        "policy": policy,
        "demand_units": demand,
        "fulfilled_units": fulfilled,
        "unmet_demand_units": state["unmet_units"],
        "unmet_demand_rate": (
            state["unmet_units"] / demand if demand > 0 else None
        ),
        "fill_rate": fulfilled / demand if demand > 0 else None,
        "stockout_days": state["stockout_pair_days"],
        "positive_demand_pair_days": denominator,
        "stockout_day_rate": (
            state["stockout_pair_days"] / denominator if denominator else None
        ),
        "expired_units": state["expired_units"],
        "expiry_cost": None,
        "expiry_waste_share_of_supply": (
            state["expired_units"] / state["supplied_units"]
            if state["supplied_units"] > 0
            else None
        ),
        "freight_cost": state["freight_cost"],
        "freight_cost_per_shipped_unit": (
            state["freight_cost"] / state["shipped_units"]
            if state["shipped_units"] > 0
            else None
        ),
        "modeled_total_cost": state["freight_cost"],
        "modeled_cost_components": ["freight"],
        "excluded_cost_components": [
            "holding_cost",
            "landed_cost_of_expiry",
            "lost_margin",
        ],
        "shipped_units": state["shipped_units"],
        "ending_warehouse_inventory_units": ending_warehouse,
        "ending_destination_inventory_units": ending_destination,
        "ending_in_transit_units": ending_in_transit,
        "ending_inventory_units": (
            ending_warehouse + ending_destination + ending_in_transit
        ),
        "constraint_violations": len(state["simulator_violations"]),
        "constraint_violation_details": state["simulator_violations"],
        "runtime_seconds": elapsed,
    }


def _simulate_policy(
    *,
    policy: str,
    inventory: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    costs: list[dict[str, Any]],
    capacities: list[dict[str, Any]],
    shelf_life: dict[str, int],
    actuals: list[dict[str, Any]],
    history: list[dict[str, Any]],
    origin: date,
    evaluation_days: int,
    solver_time_limit_seconds: int,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    elapsed_start = time.perf_counter()
    state = _new_state(inventory)
    lane_by_key = {
        (str(row["warehouse_id"]), str(row["destination_id"])): row
        for row in lanes
    }
    cost_by_key: dict[tuple[str, ...], float] = {}
    for row in costs:
        warehouse_id = str(row["warehouse_id"])
        destination_id = str(row["destination_id"])
        unit_cost = float(row["unit_transport_cost"])
        if row.get("sku_id") is not None:
            cost_by_key[(str(row["sku_id"]), warehouse_id, destination_id)] = unit_cost
        else:
            cost_by_key[(warehouse_id, destination_id)] = unit_cost
    actual_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in actuals:
        actual_by_day[_date(row["demand_date"])].append(row)
    receipt_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in receipts:
        receipt_by_day[_date(row["arrival_date"])].append(row)

    cycle_rows: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, Any]] = []
    allocation_rows: list[dict[str, Any]] = []
    history_through_origin = [
        dict(row)
        for row in history
        if _date(row["demand_date"]) <= origin
    ]

    def dispatch(dispatch_origin: date) -> None:
        visible_actuals = [
            row
            for row in actuals
            if _date(row["demand_date"]) > dispatch_origin
            and _date(row["demand_date"]) <= dispatch_origin + timedelta(days=7)
        ]
        try:
            plan, forecast_response, cycle = _make_dispatch_plans(
                policy=policy,
                demand_history=history_through_origin,
                inventory=state["warehouse"],
                destination_lots=state["destination"],
                pipeline=state["pipeline"],
                lanes=lanes,
                costs=costs,
                capacities=capacities,
                shelf_life=shelf_life,
                actuals=visible_actuals,
                origin=dispatch_origin,
                solver_time_limit_seconds=solver_time_limit_seconds,
            )
        except Exception as exc:
            cycle_rows.append(
                {
                    "policy": policy,
                    "origin": dispatch_origin.isoformat(),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return
        forecast_rows.extend(
            {
                **row,
                "policy": policy,
                "dispatch_origin": dispatch_origin.isoformat(),
            }
            for row in forecast_response["forecasts"]
        )
        cycle_rows.append(cycle)
        if plan is not None and not plan.empty:
            allocation_rows.extend(
                {
                    **json_safe(row),
                    "policy": policy,
                    "dispatch_origin": dispatch_origin.isoformat(),
                }
                for row in plan.to_dict(orient="records")
            )
            _dispatch(
                policy=policy,
                plan=plan,
                state=state,
                lanes=lane_by_key,
                costs=cost_by_key,
                shelf_life=shelf_life,
                origin=dispatch_origin,
            )

    dispatch(origin)
    for day_offset in range(evaluation_days):
        current_day = origin + timedelta(days=day_offset + 1)
        receipts_today = receipt_by_day.get(current_day, [])
        for receipt in receipt_by_day.get(current_day, []):
            state["warehouse"].append(
                {
                    "batch_id": str(receipt["batch_id"]),
                    "sku_id": str(receipt["sku_id"]),
                    "warehouse_id": str(receipt["warehouse_id"]),
                    "quantity": float(receipt["quantity"]),
                    "expiry_date": _date(receipt["expiry_date"]),
                }
            )
            state["supplied_units"] += float(receipt["quantity"])
        arrived = [
            shipment
            for shipment in state["pipeline"]
            if shipment["arrival_date"] == current_day
        ]
        state["pipeline"] = [
            shipment
            for shipment in state["pipeline"]
            if shipment["arrival_date"] != current_day
        ]
        for shipment in arrived:
            state["destination"].append(
                {
                    **shipment,
                    "quantity": float(shipment["quantity"]),
                }
            )
        expired = [
            lot
            for lot in state["warehouse"] + state["destination"]
            if lot["expiry_date"] <= current_day
        ]
        state["expired_units"] += sum(float(lot["quantity"]) for lot in expired)
        state["warehouse"] = [
            lot for lot in state["warehouse"] if lot["expiry_date"] > current_day
        ]
        state["destination"] = [
            lot for lot in state["destination"] if lot["expiry_date"] > current_day
        ]

        grouped_demand: dict[tuple[str, str], float] = defaultdict(float)
        for row in actual_by_day.get(current_day, []):
            grouped_demand[(str(row["sku_id"]), str(row["destination_id"]))] += float(
                row["quantity"]
            )
        day_demand = day_fulfilled = day_unmet = 0.0
        for (sku_id, destination_id), quantity in sorted(grouped_demand.items()):
            remaining = quantity
            lots = sorted(
                (
                    lot
                    for lot in state["destination"]
                    if lot["sku_id"] == sku_id
                    and lot["destination_id"] == destination_id
                ),
                key=lambda lot: (lot["expiry_date"], lot["batch_id"]),
            )
            for lot in lots:
                amount = min(remaining, float(lot["quantity"]))
                lot["quantity"] -= amount
                remaining -= amount
                if remaining <= 1e-9:
                    break
            fulfilled = quantity - remaining
            unmet = remaining
            day_demand += quantity
            day_fulfilled += fulfilled
            day_unmet += unmet
            state["daily"].append(
                {
                    "policy": policy,
                    "date": current_day.isoformat(),
                    "sku_id": sku_id,
                    "destination_id": destination_id,
                    "demand_units": quantity,
                    "fulfilled_units": fulfilled,
                    "unmet_demand_units": unmet,
                    "expired_units": 0.0,
                }
            )
            if quantity > 0:
                state["positive_demand_pair_days"] += 1
                if unmet > 1e-9:
                    state["stockout_pair_days"] += 1
        state["destination"] = [
            lot for lot in state["destination"] if lot["quantity"] > 1e-9
        ]
        state["demand_units"] += day_demand
        state["fulfilled_units"] += day_fulfilled
        state["unmet_units"] += day_unmet
        state["network_daily"].append(
            {
                "policy": policy,
                "date": current_day.isoformat(),
                "demand_units": day_demand,
                "fulfilled_units": day_fulfilled,
                "unmet_demand_units": day_unmet,
                "expired_units": sum(float(lot["quantity"]) for lot in expired),
                "arrived_units": sum(float(item["quantity"]) for item in arrived),
                "warehouse_receipts_units": sum(
                    float(item["quantity"]) for item in receipts_today
                ),
                "shipped_units": 0.0,
                "freight_cost": 0.0,
                "warehouse_inventory_units": sum(
                    float(lot["quantity"]) for lot in state["warehouse"]
                ),
                "destination_inventory_units": sum(
                    float(lot["quantity"]) for lot in state["destination"]
                ),
                "in_transit_units": sum(
                    float(item["quantity"]) for item in state["pipeline"]
                ),
            }
        )
        history_through_origin.extend(
            dict(row) for row in actual_by_day.get(current_day, [])
        )
        if (day_offset + 1) % 7 == 0 and day_offset + 1 < evaluation_days:
            dispatch(current_day)
        state["inventory_balances"].extend(
            {
                "policy": policy,
                "date": current_day.isoformat(),
                "location_type": location_type,
                "location_id": location_id,
                "batch_id": lot["batch_id"],
                "sku_id": lot["sku_id"],
                "quantity_units": float(lot["quantity"]),
                "expiry_date": lot["expiry_date"].isoformat(),
                "arrival_date": lot.get("arrival_date").isoformat()
                if lot.get("arrival_date")
                else None,
            }
            for location_type, location_id, lots in (
                (
                    "warehouse",
                    None,
                    state["warehouse"],
                ),
                (
                    "destination",
                    None,
                    state["destination"],
                ),
                ("in_transit", None, state["pipeline"]),
            )
            for lot in lots
            for location_id in [
                lot.get(
                    "warehouse_id"
                    if location_type == "warehouse"
                    else "destination_id",
                    "",
                )
            ]
            if lot["quantity"] > 1e-9
        )

    metrics = _metric_row(policy, state, time.perf_counter() - elapsed_start)
    return (
        metrics,
        state["daily"],
        [
            *cycle_rows,
            {
                "policy": policy,
                "forecasts": forecast_rows,
                "network_daily": state["network_daily"],
                "inventory_balances": state["inventory_balances"],
                "simulator_violations": state["simulator_violations"],
            },
        ],
        allocation_rows,
    )


def _dispatch(
    *,
    policy: str,
    plan: pd.DataFrame,
    state: dict[str, Any],
    lanes: dict[tuple[str, str], dict[str, Any]],
    costs: dict[tuple[str, ...], float],
    shelf_life: dict[str, int],
    origin: date,
) -> None:
    warehouse_by_id = {row["batch_id"]: row for row in state["warehouse"]}
    for _, row in plan.iterrows():
        quantity = float(row["allocated_quantity"])
        if quantity <= 1e-9:
            continue
        batch_id = str(row["batch_id"])
        sku_id = str(row["sku_id"])
        warehouse_id = str(row["warehouse_id"])
        destination_id = str(row["destination_id"])
        lane = lanes.get((warehouse_id, destination_id))
        batch = warehouse_by_id.get(batch_id)
        if lane is None or not bool(lane["is_available"]):
            state["simulator_violations"].append(
                {"policy": policy, "check": "lane_eligibility", "batch_id": batch_id}
            )
            continue
        if batch is None or quantity > float(batch["quantity"]) + 1e-7:
            state["simulator_violations"].append(
                {"policy": policy, "check": "batch_balance", "batch_id": batch_id}
            )
            continue
        arrival = origin + timedelta(days=int(lane.get("transit_days", 1)))
        remaining_life = (batch["expiry_date"] - arrival).days
        if remaining_life < int(shelf_life[sku_id]):
            state["simulator_violations"].append(
                {"policy": policy, "check": "shelf_life", "batch_id": batch_id}
            )
            continue
        cost_key = (sku_id, warehouse_id, destination_id)
        unit_cost = costs.get(cost_key)
        if unit_cost is None:
            unit_cost = costs.get((warehouse_id, destination_id))
        if unit_cost is None:
            state["simulator_violations"].append(
                {"policy": policy, "check": "missing_freight", "batch_id": batch_id}
            )
            continue
        batch["quantity"] -= quantity
        if batch["quantity"] < -1e-7:
            state["simulator_violations"].append(
                {"policy": policy, "check": "negative_inventory", "batch_id": batch_id}
            )
            batch["quantity"] = 0.0
        state["shipped_units"] += quantity
        state["freight_cost"] += quantity * unit_cost
        shipment = {
            "batch_id": batch_id,
            "sku_id": sku_id,
            "warehouse_id": warehouse_id,
            "destination_id": destination_id,
            "quantity": quantity,
            "expiry_date": batch["expiry_date"],
            "arrival_date": arrival,
            "unit_transport_cost": unit_cost,
        }
        state["pipeline"].append(shipment)
        state["network_daily"].append(
            {
                "policy": policy,
                "date": origin.isoformat(),
                "demand_units": 0.0,
                "fulfilled_units": 0.0,
                "unmet_demand_units": 0.0,
                "expired_units": 0.0,
                "arrived_units": 0.0,
                "shipped_units": quantity,
                "freight_cost": quantity * unit_cost,
                "warehouse_inventory_units": sum(
                    float(item["quantity"]) for item in state["warehouse"]
                ),
                "destination_inventory_units": sum(
                    float(item["quantity"]) for item in state["destination"]
                ),
                "in_transit_units": sum(
                    float(item["quantity"]) for item in state["pipeline"]
                ),
            }
        )
    state["warehouse"] = [
        lot for lot in state["warehouse"] if lot["quantity"] > 1e-9
    ]


def _forecast_metrics(daily: list[dict[str, Any]]) -> dict[str, Any]:
    if not daily:
        return {
            "observation_count": 0,
            "mae_units": None,
            "rmse_units": None,
            "wape": None,
            "weekly_wape": None,
            "bias": None,
            "bias_units": None,
            "interval_coverage": None,
            "mean_interval_width_units": None,
            "unmatched_actual_rows": None,
        }
    actual = np.asarray([float(row["actual"]) for row in daily], dtype=float)
    predicted = np.asarray([float(row["point_forecast"]) for row in daily], dtype=float)
    errors = predicted - actual
    denominator = float(np.abs(actual).sum())
    weekly_pairs: dict[tuple[str, str, str], list[float]] = defaultdict(
        lambda: [0.0, 0.0]
    )
    for row in daily:
        if row.get("dispatch_origin") is None:
            continue
        key = (
            str(row.get("sku_id", "")),
            str(row.get("destination_id", "")),
            str(row["dispatch_origin"]),
        )
        weekly_pairs[key][0] += float(row["actual"])
        weekly_pairs[key][1] += float(row["point_forecast"])
    weekly_actual = np.asarray([pair[0] for pair in weekly_pairs.values()])
    weekly_predicted = np.asarray([pair[1] for pair in weekly_pairs.values()])
    weekly_denominator = float(np.abs(weekly_actual).sum())
    weekly_wape = (
        float(np.abs(weekly_actual - weekly_predicted).sum() / weekly_denominator)
        if weekly_denominator
        else None
    )
    covered = [
        float(row["lower_bound"]) <= float(row["actual"]) <= float(row["upper_bound"])
        for row in daily
        if row.get("lower_bound") is not None and row.get("upper_bound") is not None
    ]
    interval_widths = [
        float(row["upper_bound"]) - float(row["lower_bound"])
        for row in daily
        if row.get("lower_bound") is not None and row.get("upper_bound") is not None
    ]
    return {
        "observation_count": len(daily),
        "mae_units": float(np.mean(np.abs(errors))),
        "rmse_units": float(np.sqrt(np.mean(np.square(errors)))),
        "wape": float(np.abs(errors).sum() / denominator) if denominator else None,
        "weekly_wape": weekly_wape,
        "bias": float(errors.sum() / denominator) if denominator else None,
        "bias_units": float(np.mean(errors)),
        "interval_coverage": float(np.mean(covered)) if covered else None,
        "interval_observation_count": len(covered),
        "mean_interval_width_units": (
            float(np.mean(interval_widths)) if interval_widths else None
        ),
        "unmatched_actual_rows": None,
    }


def run_backtest(
    *,
    demand_history: list[dict[str, Any]],
    inventory_batches: list[dict[str, Any]],
    warehouse_receipts: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    transport_costs: list[dict[str, Any]],
    capacities: list[dict[str, Any]],
    sku_min_shelf_life_days: dict[str, int],
    evaluation_actuals: list[dict[str, Any]],
    as_of: date | None = None,
    evaluation_days: int = 56,
    solver_time_limit_seconds: int = 60,
    synthetic: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run the engine's three policies over a strict rolling-origin window."""
    engine = _load_engine()
    config = engine["EngineConfig"](
        forecast=engine["ForecastConfig"](horizon_days=7)
    )
    history_frame = engine["validate_demand"](
        frame_from_rows(demand_history), config=config
    ).frame
    actual_frame = engine["validate_demand"](
        frame_from_rows(evaluation_actuals), config=config
    ).frame
    latest_history_date = pd.to_datetime(
        history_frame[config.columns.demand_date]
    ).max().date()
    origin = as_of or latest_history_date
    history_frame = history_frame.loc[
        pd.to_datetime(history_frame[config.columns.demand_date]).dt.date <= origin
    ].copy()
    if history_frame.empty:
        raise ValueError("No historical demand is available on or before as_of.")
    expected_days = [origin + timedelta(days=offset) for offset in range(1, evaluation_days + 1)]
    observed_days = sorted(
        pd.to_datetime(actual_frame[config.columns.demand_date]).dt.date.unique()
    )
    if observed_days != expected_days:
        raise ValueError(
            "Evaluation actuals must cover every day immediately after the history origin "
            "through evaluation_days, with no gaps or extra dates."
        )
    if len(actual_frame) and (
        pd.to_datetime(actual_frame[config.columns.demand_date]).dt.date.min()
        <= origin
    ):
        raise ValueError("Evaluation actuals must be strictly after the training origin.")
    if len({str(row["batch_id"]) for row in inventory_batches}) != len(inventory_batches):
        raise ValueError("Initial inventory batch IDs must be unique.")
    inventory_ids = {str(row["batch_id"]) for row in inventory_batches}
    receipt_ids = [str(row["batch_id"]) for row in warehouse_receipts]
    if len(set(receipt_ids)) != len(receipt_ids) or inventory_ids.intersection(receipt_ids):
        raise ValueError("Receipt batch IDs must be unique and distinct from initial batches.")
    actual_rows = json_safe(actual_frame)
    initial_receipts = [
        row for row in warehouse_receipts if _date(row["arrival_date"]) <= origin
    ]
    future_receipts = [
        row for row in warehouse_receipts if _date(row["arrival_date"]) > origin
    ]
    starting_inventory = _eligible_inventory(
        inventory_batches, initial_receipts, origin
    )
    base_data = {
        "demand_history": json_safe(history_frame),
        "inventory_batches": inventory_batches,
        "warehouse_receipts": warehouse_receipts,
        "lanes": lanes,
        "transport_costs": transport_costs,
        "capacities": capacities,
        "sku_min_shelf_life_days": sku_min_shelf_life_days,
    }
    policy_metrics: list[dict[str, Any]] = []
    policy_daily: list[dict[str, Any]] = []
    policy_cycles: list[dict[str, Any]] = []
    policy_forecasts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    allocation_rows: list[dict[str, Any]] = []
    network_daily: list[dict[str, Any]] = []
    inventory_balances: list[dict[str, Any]] = []
    for policy in POLICY_NAMES:
        try:
            metrics, daily, details, allocations = _simulate_policy(
                policy=policy,
                inventory=starting_inventory,
                receipts=future_receipts,
                lanes=lanes,
                costs=transport_costs,
                capacities=capacities,
                shelf_life=sku_min_shelf_life_days,
                actuals=actual_rows,
                history=base_data["demand_history"],
                origin=origin,
                evaluation_days=evaluation_days,
                solver_time_limit_seconds=solver_time_limit_seconds,
            )
            policy_metrics.append(metrics)
            policy_daily.extend(daily)
            allocation_rows.extend(allocations)
            cycle_details = [item for item in details if "origin" in item]
            policy_cycles.extend(cycle_details)
            cycle_forecasts = next(
                (item["forecasts"] for item in details if "forecasts" in item),
                [],
            )
            policy_forecasts[policy].extend(cycle_forecasts)
            network_rows = next(
                (item["network_daily"] for item in details if "network_daily" in item),
                [],
            )
            network_daily.extend(network_rows)
            inventory_rows = next(
                (
                    item["inventory_balances"]
                    for item in details
                    if "inventory_balances" in item
                ),
                [],
            )
            inventory_balances.extend(inventory_rows)
        except Exception as exc:
            policy_cycles.append(
                {
                    "policy": policy,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    actual_lookup = {
        (
            str(row["sku_id"]),
            str(row["destination_id"]),
            _date(row["demand_date"]).isoformat(),
        ): float(row["quantity"])
        for row in actual_rows
    }
    forecast_metrics: dict[str, Any] = {}
    all_forecasts: list[dict[str, Any]] = []
    for policy, rows in policy_forecasts.items():
        matched: list[dict[str, Any]] = []
        for row in rows:
            key = (
                str(row["sku_id"]),
                str(row["destination_id"]),
                _date(row["forecast_date"]).isoformat(),
            )
            actual = actual_lookup.get(key)
            if actual is None:
                continue
            matched.append(
                {
                    "actual": actual,
                    "point_forecast": row["point_forecast"],
                    "lower_bound": row.get("lower_bound"),
                    "upper_bound": row.get("upper_bound"),
                    "dispatch_origin": row.get("dispatch_origin"),
                }
            )
            all_forecasts.append(
                {
                    **row,
                    "actual": actual,
                    "policy": policy,
                }
            )
        metrics = _forecast_metrics(matched)
        metrics["unmatched_actual_rows"] = max(0, len(actual_rows) - len(matched))
        forecast_metrics[policy] = metrics
    partial = len(policy_metrics) != len(POLICY_NAMES) or any(
        cycle.get("verification", {}).get("is_valid") is False
        or cycle.get("status") == "failed"
        for cycle in policy_cycles
    )
    gain_decomposition: dict[str, Any] = {}
    by_policy = {row["policy"]: row for row in policy_metrics}
    for metric in ("unmet_demand_rate", "expired_units", "modeled_total_cost"):
        gain_decomposition[metric] = {}
        for baseline in ("cheapest_first", "fefo_first"):
            if baseline not in by_policy or "optiqo" not in by_policy:
                gain_decomposition[metric][baseline] = None
                continue
            baseline_value = by_policy[baseline].get(metric)
            optimizer_value = by_policy["optiqo"].get(metric)
            gain_decomposition[metric][baseline] = {
                "absolute_difference_optiqo_minus_baseline": (
                    optimizer_value - baseline_value
                    if optimizer_value is not None and baseline_value is not None
                    else None
                ),
                "relative_reduction": (
                    (baseline_value - optimizer_value) / baseline_value
                    if baseline_value not in (None, 0) and optimizer_value is not None
                    else None
                ),
            }
    return json_safe(
        {
            "status": "partial_failure" if partial else "succeeded",
            "synthetic": synthetic,
            "seed": seed,
            "evaluation_days": evaluation_days,
            "evaluation_start": expected_days[0],
            "evaluation_end": expected_days[-1],
            "policies": list(POLICY_NAMES),
            "policy_metrics": policy_metrics,
            "forecast_metrics": forecast_metrics,
            "forecasts": all_forecasts,
            "allocations": allocation_rows,
            "gain_decomposition": gain_decomposition,
            "cycles": policy_cycles,
            "daily": policy_daily,
            "daily_inventory": inventory_balances,
            "daily_network": network_daily,
            "assumptions": [
                "The 56-day evaluation is chronological; each seven-day forecast and allocation uses only history through that dispatch date.",
                "Daily order is: receive scheduled warehouse receipts and due shipments; expire lots whose expiry date is today or earlier; fulfill realized demand from destination stock FEFO; dispatch the next weekly plan.",
                "Demand is lost rather than backordered. No replenishment is created automatically; only supplied warehouse_receipts are applied.",
                "Destination opening inventory is absent from the current shared input contract and is therefore zero. In-transit shipments are included when reducing future forecast demand and destination capacity.",
                "The optimizer, cheapest-first, and FEFO-first plans use the same engine eligibility, forecast, stock, lanes, capacities, receipts, realized demand, and freight inputs on their respective policy trajectories.",
                "Freight is the only monetary component available. Holding cost, expiry landed cost, and lost margin are unavailable and excluded; expiry units are measured directly.",
                "The engine exposes cheapest-first and FEFO-first allocation baselines, not the PRD-specific nearest-warehouse B1 and same-forecast B2 policies.",
                "A single dataset is evaluated per request; results are simulation measurements and are not verified real-world savings.",
                f"History rows after the selected origin ({origin.isoformat()}) are excluded from all model fitting.",
            ],
        }
    )
