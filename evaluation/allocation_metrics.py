"""Service, expiry, and freight metrics for allocation plans."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from ..schemas import validate_inventory_batches, validate_transport_costs


def allocation_metrics(
    plan: pd.DataFrame,
    actual_demand: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    transport_costs: pd.DataFrame | None = None,
    *,
    as_of: str | date | pd.Timestamp | None = None,
    horizon_days: int = 7,
    config: EngineConfig | None = None,
) -> dict[str, Any]:
    """Measure a plan against held-out actual demand and available cost data.

    ``actual_demand`` must have SKU, destination, and quantity columns; multiple
    rows at the same grain are summed. Expiry waste is estimable only when an
    origin date and batch expiry dates are present. No unmet-demand or expiry
    penalty is invented; ``modeled_total_cost`` includes freight only.
    """
    cfg = config or EngineConfig()
    cols = cfg.columns
    required_plan = {cols.batch_id, cols.sku_id, cols.warehouse_id, cols.destination_id, "allocated_quantity"}
    missing = required_plan - set(plan.columns)
    if missing:
        raise SchemaError("Plan is missing required columns.", details={"missing_columns": sorted(missing)})
    required_demand = {cols.sku_id, cols.destination_id, cols.quantity}
    missing = required_demand - set(actual_demand.columns)
    if missing:
        raise SchemaError("Actual demand is missing required columns.", details={"missing_columns": sorted(missing)})

    result_plan = plan.copy()
    result_plan["allocated_quantity"] = pd.to_numeric(result_plan["allocated_quantity"], errors="coerce")
    if (
        result_plan["allocated_quantity"].isna().any()
        or (~result_plan["allocated_quantity"].map(lambda value: math.isfinite(float(value)))).any()
        or (result_plan["allocated_quantity"] < 0).any()
    ):
        raise ValidationError("Allocated quantities must be finite and non-negative.")

    actual = actual_demand[[cols.sku_id, cols.destination_id, cols.quantity]].copy()
    actual[cols.quantity] = pd.to_numeric(actual[cols.quantity], errors="coerce")
    if (
        actual[cols.quantity].isna().any()
        or (~actual[cols.quantity].map(lambda value: math.isfinite(float(value)))).any()
        or (actual[cols.quantity] < 0).any()
    ):
        raise ValidationError("Actual demand must be finite and non-negative.")
    actual_total = float(actual[cols.quantity].sum())
    allocated_total = float(result_plan["allocated_quantity"].sum())

    actual_by_pair = actual.groupby([cols.sku_id, cols.destination_id])[cols.quantity].sum()
    allocated_by_pair = result_plan.groupby([cols.sku_id, cols.destination_id])["allocated_quantity"].sum()
    unmet = 0.0
    for key, demand in actual_by_pair.items():
        unmet += max(0.0, float(demand) - float(allocated_by_pair.get(key, 0.0)))

    inventory = validate_inventory_batches(inventory_batches, config=cfg).frame
    batch_allocated = result_plan.groupby(cols.batch_id)["allocated_quantity"].sum()
    expiry_waste: float | None = None
    if as_of is not None and cols.expiry_date in inventory.columns:
        origin = pd.Timestamp(as_of).normalize()
        horizon_end = origin + pd.Timedelta(days=horizon_days)
        expiry_waste = 0.0
        for _, batch in inventory.iterrows():
            if batch[cols.expiry_date] <= horizon_end:
                shipped = float(batch_allocated.get(batch[cols.batch_id], 0.0))
                expiry_waste += max(0.0, float(batch[cols.quantity]) - shipped)

    freight_cost: float | None = None
    if transport_costs is not None:
        validated_costs = validate_transport_costs(transport_costs, config=cfg).frame
        sku_costs = cols.sku_id in validated_costs.columns
        cost_keys = [cols.warehouse_id, cols.destination_id]
        if sku_costs:
            cost_keys.insert(0, cols.sku_id)
        cost_lookup = {
            tuple(row[key] for key in cost_keys): float(row[cols.unit_transport_cost])
            for row in validated_costs.to_dict("records")
        }
        freight_cost = 0.0
        for _, row in result_plan.iterrows():
            key = tuple(row[column] for column in cost_keys)
            if key not in cost_lookup:
                raise ValidationError("A shipment has no matching transport cost.", details={"cost_key": key})
            freight_cost += float(row["allocated_quantity"]) * cost_lookup[key]

    service_level = 1.0 if actual_total == 0 else max(0.0, 1.0 - unmet / actual_total)
    return {
        "actual_demand": actual_total,
        "allocated_quantity": allocated_total,
        "unmet_demand": unmet,
        "service_level": service_level,
        "expiry_waste": expiry_waste,
        "freight_cost": freight_cost,
        "modeled_total_cost": freight_cost,
        "modeled_cost_components": ["freight"] if freight_cost is not None else [],
        "excluded_cost_components": ["unmet_demand_penalty", "expiry_loss", "holding_cost"],
    }
