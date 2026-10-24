
"""Evidence-based explanations for Optiqo allocation decisions."""

from __future__ import annotations

import math
import pandas as pd

from ..exceptions import SchemaError, ValidationError


def explain_allocation(
    plan: pd.DataFrame,
    eligible: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    capacities: pd.DataFrame | None = None,
    demand_forecast: pd.DataFrame | None = None,
    transport_costs: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Explain allocations using inventory, eligibility, demand and cost data.

    Returns one explanation row for every eligible candidate, including
    candidates that received zero allocation.

    The function reports evidence; it does not claim that a constraint
    caused a decision unless the available data demonstrates that limit.
    """
    required_plan = {
        "batch_id", "sku_id", "warehouse_id",
        "destination_id", "allocated_quantity",
    }
    required_eligible = {
        "batch_id", "sku_id", "warehouse_id",
        "destination_id", "quantity",
    }
    required_inventory = {"batch_id", "quantity"}

    for name, frame in (
        ("plan", plan),
        ("eligible", eligible),
        ("inventory_batches", inventory_batches),
    ):
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{name} must be a pandas DataFrame.")

    missing = required_plan - set(plan.columns)
    if missing:
        raise SchemaError(f"Plan is missing columns: {sorted(missing)}")

    missing = required_eligible - set(eligible.columns)
    if missing:
        raise SchemaError(f"Eligible data is missing columns: {sorted(missing)}")

    missing = required_inventory - set(inventory_batches.columns)
    if missing:
        raise SchemaError(
            f"Inventory is missing columns: {sorted(missing)}"
        )

    if not eligible.index.is_unique:
        raise ValidationError("Eligible dataframe index must be unique.")

    plan = plan.copy()
    eligible = eligible.copy()
    inventory = inventory_batches.copy()

    plan["allocated_quantity"] = pd.to_numeric(
        plan["allocated_quantity"], errors="coerce"
    )
    if (
        plan["allocated_quantity"].isna().any()
        or (~plan["allocated_quantity"].map(math.isfinite)).any()
        or (plan["allocated_quantity"] < 0).any()
    ):
        raise ValidationError(
            "Allocated quantities must be finite and non-negative."
        )

    # Validate inventory identifiers and quantities.
    if inventory["batch_id"].duplicated().any():
        raise ValidationError("Inventory batch_id must be unique.")

    stock_values = pd.to_numeric(inventory["quantity"], errors="coerce")
    if (
        stock_values.isna().any()
        or (~stock_values.map(math.isfinite)).any()
        or (stock_values < 0).any()
    ):
        raise ValidationError("Inventory quantities must be finite and non-negative.")

    inventory["quantity"] = stock_values
    stock_by_batch = inventory.set_index("batch_id")["quantity"].to_dict()

    # Match allocation rows to eligible candidate rows.
    keys = ["batch_id", "sku_id", "warehouse_id", "destination_id"]

    if "eligible_row_id" in plan.columns:
        unknown = ~plan["eligible_row_id"].isin(eligible.index)
        if unknown.any():
            raise ValidationError(
                "Plan contains eligible_row_id values not found in eligible data."
            )

        allocated_by_candidate = plan.groupby(
            "eligible_row_id"
        )["allocated_quantity"].sum().to_dict()
    else:
        # Without candidate IDs, identical candidate keys are ambiguous.
        if eligible.duplicated(keys).any():
            raise ValidationError(
                "Eligible rows contain duplicate shipment keys. "
                "Keep eligible_row_id in the plan to explain them safely."
            )

        allocated_by_candidate = {}
        key_to_id = {
            tuple(row[column] for column in keys): row_id
            for row_id, row in eligible.iterrows()
        }
        for _, row in plan.iterrows():
            key = tuple(row[column] for column in keys)
            if key not in key_to_id:
                raise ValidationError(
                    f"Plan row {key} is not present in eligible candidates."
                )
            candidate_id = key_to_id[key]
            allocated_by_candidate[candidate_id] = (
                allocated_by_candidate.get(candidate_id, 0.0)
                + float(row["allocated_quantity"])
            )

    # Aggregate destination/SKU forecast demand.
    demand_by_pair = {}
    if demand_forecast is not None:
        required = {"sku_id", "destination_id", "point_forecast"}
        if required - set(demand_forecast.columns):
            raise SchemaError(
                "Demand forecast requires sku_id, destination_id, point_forecast."
            )

        demand = demand_forecast.copy()
        demand["point_forecast"] = pd.to_numeric(
            demand["point_forecast"], errors="coerce"
        )
        if (
            demand["point_forecast"].isna().any()
            or (~demand["point_forecast"].map(math.isfinite)).any()
            or (demand["point_forecast"] < 0).any()
        ):
            raise ValidationError(
                "Forecast demand must be finite and non-negative."
            )

        demand_by_pair = (
            demand.groupby(["sku_id", "destination_id"])["point_forecast"]
            .sum()
            .to_dict()
        )

    allocated_by_pair = {}
    for _, row in plan.iterrows():
        key = (row["sku_id"], row["destination_id"])
        allocated_by_pair[key] = (
            allocated_by_pair.get(key, 0.0)
            + float(row["allocated_quantity"])
        )

    # Aggregate destination capacity when provided.
    capacity_by_key = {}
    capacity_allocated_by_key = {}
    if capacities is not None:
        if not {"destination_id", "capacity_units"}.issubset(capacities.columns):
            raise SchemaError(
                "Capacities require destination_id and capacity_units."
            )

        capacity_keys = ["destination_id"]
        if "sku_id" in capacities.columns:
            capacity_keys.append("sku_id")

        if capacities.duplicated(capacity_keys).any():
            raise ValidationError(
                "Duplicate capacity groups exist. Resolve SKU/warehouse/"
                "effective-date capacity rules before explaining them."
            )

        for _, row in capacities.iterrows():
            key = tuple(row[column] for column in capacity_keys)
            if len(key) == 1:
                key = key[0]
            capacity_by_key[key] = float(row["capacity_units"])

        for _, row in plan.iterrows():
            key = tuple(row[column] for column in capacity_keys)
            if len(key) == 1:
                key = key[0]
            capacity_allocated_by_key[key] = (
                capacity_allocated_by_key.get(key, 0.0)
                + float(row["allocated_quantity"])
            )

    # Optional freight evidence.
    cost_by_lane = {}
    if transport_costs is not None:
        required = {
            "warehouse_id", "destination_id", "unit_transport_cost"
        }
        if not required.issubset(transport_costs.columns):
            raise SchemaError(
                "Transport costs require warehouse_id, destination_id, "
                "and unit_transport_cost."
            )

        costs = transport_costs.copy()
        costs["unit_transport_cost"] = pd.to_numeric(
            costs["unit_transport_cost"], errors="coerce"
        )
        if (
            costs["unit_transport_cost"].isna().any()
            or (~costs["unit_transport_cost"].map(math.isfinite)).any()
            or (costs["unit_transport_cost"] < 0).any()
        ):
            raise ValidationError(
                "Transport costs must be finite and non-negative."
            )

        cost_keys = ["warehouse_id", "destination_id"]
        if "sku_id" in costs.columns:
            cost_keys.insert(0, "sku_id")

        if costs.duplicated(cost_keys).any():
            raise ValidationError(
                "Transport cost rows have duplicate lane/SKU keys."
            )

        for _, row in costs.iterrows():
            key = tuple(row[column] for column in cost_keys)
            cost_by_lane[key] = float(row["unit_transport_cost"])

    explanations = []

    for candidate_id, row in eligible.iterrows():
        batch_id = row["batch_id"]
        sku_id = row["sku_id"]
        warehouse_id = row["warehouse_id"]
        destination_id = row["destination_id"]

        allocated = float(allocated_by_candidate.get(candidate_id, 0.0))
        candidate_quantity = float(row["quantity"])
        batch_stock = stock_by_batch.get(batch_id)

        pair = (sku_id, destination_id)
        forecast = demand_by_pair.get(pair)
        pair_allocated = allocated_by_pair.get(pair, 0.0)

        messages = [
            f"Allocated {allocated:g} of "
            f"{candidate_quantity:g} eligible candidate units."
        ]

        if batch_stock is not None:
            batch_total = float(
                plan.loc[
                    plan["batch_id"] == batch_id, "allocated_quantity"
                ].sum()
            )
            messages.append(
                f"Batch stock is {batch_stock:g}; "
                f"total allocation from this batch is {batch_total:g}."
            )
        else:
            batch_total = None
            messages.append("Inventory stock for this batch was not found.")

        if forecast is not None:
            messages.append(
                f"Forecast demand for this SKU/destination is {forecast:g}; "
                f"total allocation to it is {pair_allocated:g}."
            )

        capacity_key = (
            (destination_id, sku_id)
            if capacities is not None and "sku_id" in capacities.columns
            else destination_id
        )
        capacity = capacity_by_key.get(capacity_key)
        capacity_total = capacity_allocated_by_key.get(capacity_key)

        if capacity is not None:
            messages.append(
                f"Recorded capacity is {capacity:g}; "
                f"allocation in this capacity group is "
                f"{capacity_total:g}."
            )

        remaining_shelf_life = row.get(
            "remaining_shelf_life_days_at_arrival"
        )
        minimum_shelf_life = row.get("minimum_shelf_life_days")
        if pd.notna(remaining_shelf_life):
            message = (
                f"Remaining shelf life at arrival is "
                f"{remaining_shelf_life} days."
            )
            if pd.notna(minimum_shelf_life):
                message += f" Required minimum is {minimum_shelf_life} days."
            messages.append(message)

        lane_cost = None
        allocated_freight = None
        transport_cost_status = "not_provided"
        if cost_by_lane:
            cost_key = (
                (sku_id, warehouse_id, destination_id)
                if transport_costs is not None
                and "sku_id" in transport_costs.columns
                else (warehouse_id, destination_id)
            )
            lane_cost = cost_by_lane.get(cost_key)
            if lane_cost is not None:
                allocated_freight = allocated * lane_cost
                transport_cost_status = "available"
                messages.append(
                    f"Unit transport cost on this lane is {lane_cost:g}; "
                    f"freight for this allocation is {allocated_freight:g}."
                )
            else:
                transport_cost_status = "missing"
                messages.append("No applicable transport-cost record was supplied for this candidate.")
        elif transport_costs is not None:
            transport_cost_status = "missing"
            messages.append("No applicable transport-cost record was supplied for this candidate.")

        if allocated <= 1e-9:
            messages.append(
                "No units were allocated to this candidate. "
                "These facts describe the available limits; they do not by "
                "themselves prove which factor caused the optimizer's decision."
            )
        elif candidate_quantity - allocated > 1e-6:
            messages.append(
                f"{candidate_quantity - allocated:g} candidate units were "
                "not allocated on this shipment option."
            )

        explanations.append(
            {
                "eligible_row_id": candidate_id,
                "batch_id": batch_id,
                "sku_id": sku_id,
                "warehouse_id": warehouse_id,
                "destination_id": destination_id,
                "eligible_quantity": candidate_quantity,
                "allocated_quantity": allocated,
                "unallocated_candidate_quantity": max(
                    0.0, candidate_quantity - allocated
                ),
                "batch_stock": batch_stock,
                "batch_total_allocated": batch_total,
                "forecast_demand": forecast,
                "destination_sku_total_allocated": pair_allocated,
                "capacity_units": capacity,
                "capacity_group_allocated": capacity_total,
                "arrival_date": row.get("arrival_date"),
                "remaining_shelf_life_days_at_arrival": remaining_shelf_life,
                "minimum_shelf_life_days": minimum_shelf_life,
                "unit_transport_cost": lane_cost,
                "allocated_freight_cost": allocated_freight,
                "transport_cost_status": transport_cost_status,
                "explanation": " ".join(messages),
            }
        )

    return pd.DataFrame(explanations)
