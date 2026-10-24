
"""Stock, destination capacity, and demand constraints for allocation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd
import pulp

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from ..schemas import validate_capacities, validate_inventory_batches


def add_constraints(
    problem: pulp.LpProblem,
    decision_vars: Mapping[Any, pulp.LpVariable],
    eligible: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    capacities: pd.DataFrame | None = None,
    demand_forecast: pd.DataFrame | None = None,
    *,
    config: EngineConfig | None = None,
    as_of: str | date | pd.Timestamp | None = None,
) -> list[pulp.LpConstraint]:
    """Add stock, capacity, and forecast-demand limits to an LP problem.

    Contract:
    - Each decision variable represents shipment quantity for one row
      in `eligible`.
    - Decision-variable keys must match eligible DataFrame index labels.
    - `eligible` must contain batch_id, sku_id, destination_id and quantity.
    - `quantity` in eligible is the available stock for that batch.
    - Capacities, when supplied, must use the configured capacity schema.
    - Demand forecasts, when supplied, must contain sku_id,
      destination_id and point_forecast. Forecast rows are summed by
      SKU and destination before applying the shipment upper bound.

    This function adds constraints only. It does not solve the model.
    """
    if not isinstance(problem, pulp.LpProblem):
        raise TypeError("problem must be a PuLP LpProblem.")

    if not isinstance(eligible, pd.DataFrame):
        raise TypeError("eligible must be a pandas DataFrame.")

    if not isinstance(decision_vars, Mapping):
        raise TypeError("decision_vars must be a mapping.")

    cfg = config or EngineConfig()
    cols = cfg.columns

    required_eligible = [
        cols.batch_id,
        cols.sku_id,
        cols.destination_id,
        cols.quantity,
    ]
    missing = [c for c in required_eligible if c not in eligible.columns]
    if missing:
        raise SchemaError(
            "Eligible shipments are missing required columns.",
            details={"missing_columns": missing},
        )

    if eligible.empty:
        if decision_vars:
            raise ValidationError(
                "Decision variables were supplied for an empty eligible-shipment frame."
            )
        return []

    if not eligible.index.is_unique:
        raise ValidationError("Eligible shipment index labels must be unique.")

    eligible_keys = set(eligible.index)
    variable_keys = set(decision_vars.keys())
    if eligible_keys != variable_keys:
        raise ValidationError(
            "Decision-variable keys must exactly match eligible DataFrame index labels.",
            details={
                "missing_variable_keys": list(eligible_keys - variable_keys)[:10],
                "extra_variable_keys": list(variable_keys - eligible_keys)[:10],
            },
        )

    batches = validate_inventory_batches(
        inventory_batches, config=cfg
    ).frame

    stock_by_batch = batches.set_index(cols.batch_id)[cols.quantity].to_dict()
    inventory_lookup = batches.set_index(cols.batch_id)

    # A batch's authoritative stock comes from inventory_batches, not
    # from a possibly stale quantity copied into the eligible frame.
    unknown_batches = sorted(
        set(eligible[cols.batch_id].astype(str)) - set(stock_by_batch)
    )
    if unknown_batches:
        raise ValidationError(
            "Eligible shipments reference unknown inventory batches.",
            details={"unknown_batch_ids": unknown_batches[:10]},
        )
    for _, row in eligible.iterrows():
        batch_id = str(row[cols.batch_id])
        stock_row = inventory_lookup.loc[batch_id]
        for column in (cols.sku_id, cols.warehouse_id):
            if str(row[column]) != str(stock_row[column]):
                raise ValidationError(
                    f"Eligible {column} does not match its inventory batch.",
                    details={"batch_id": batch_id, "eligible": str(row[column]), "inventory": str(stock_row[column])},
                )

    shipment_rows = eligible.copy()
    shipment_rows[cols.batch_id] = shipment_rows[cols.batch_id].astype(str)
    shipment_rows[cols.sku_id] = shipment_rows[cols.sku_id].astype(str)
    shipment_rows[cols.destination_id] = shipment_rows[
        cols.destination_id
    ].astype(str)

    constraints: list[pulp.LpConstraint] = []

    # 1. Total quantity shipped from each batch cannot exceed its stock.
    for batch_id, group in shipment_rows.groupby(cols.batch_id, sort=False):
        expression = pulp.lpSum(
            decision_vars[idx] for idx in group.index
        )
        constraint = expression <= float(stock_by_batch[batch_id])
        problem += constraint, f"stock_{len(constraints)}"
        constraints.append(constraint)

    # 2. Optional destination capacity limits.
    if capacities is not None:
        validated_capacity = validate_capacities(
            capacities, config=cfg
        ).frame
        capacity_dimensions = [cols.destination_id]
        capacity_dimensions.extend(
            key for key in (cols.sku_id, cols.warehouse_id)
            if key in validated_capacity.columns
        )

        if cols.effective_date in validated_capacity.columns:
            if as_of is None:
                if demand_forecast is not None and cols.forecast_origin in demand_forecast.columns:
                    origins = pd.to_datetime(demand_forecast[cols.forecast_origin], errors="coerce").dropna()
                    if origins.empty:
                        raise ValidationError("Capacity effective-date selection requires a valid as_of date.")
                    capacity_as_of = origins.max().normalize()
                else:
                    raise ValidationError("Capacity effective-date selection requires as_of.")
            else:
                capacity_as_of = pd.Timestamp(as_of).normalize()
            validated_capacity = validated_capacity.loc[
                validated_capacity[cols.effective_date] <= capacity_as_of
            ].copy()
            if validated_capacity.empty:
                raise ValidationError("No capacity record is effective on or before as_of.")
            latest = validated_capacity.groupby(capacity_dimensions)[cols.effective_date].transform("max")
            validated_capacity = validated_capacity.loc[
                validated_capacity[cols.effective_date] == latest
            ].copy()

        if validated_capacity.duplicated(capacity_dimensions).any():
            raise ValidationError(
                "Capacity records are ambiguous for the applicable dimensions.",
                details={"dimensions": capacity_dimensions},
            )
        capacity_map = {
            tuple(row[key] for key in capacity_dimensions): float(row[cols.capacity_units])
            for row in validated_capacity.to_dict("records")
        }
        for group_key, group in shipment_rows.groupby(capacity_dimensions, sort=False):
            if not isinstance(group_key, tuple):
                group_key = (group_key,)
            capacity = capacity_map.get(group_key)
            if capacity is None:
                raise ValidationError(
                    "No applicable capacity record exists for an eligible shipment group.",
                    details={"capacity_key": group_key},
                )
            expression = pulp.lpSum(decision_vars[idx] for idx in group.index)
            constraint = expression <= capacity
            problem += constraint, f"capacity_{len(constraints)}"
            constraints.append(constraint)

    # 3. Optional demand ceiling for each SKU/destination pair.
    if demand_forecast is not None:
        required_forecast = [
            cols.sku_id,
            cols.destination_id,
            cols.point_forecast,
        ]
        missing = [
            c for c in required_forecast if c not in demand_forecast.columns
        ]
        if missing:
            raise SchemaError(
                "Demand forecast is missing required columns.",
                details={"missing_columns": missing},
            )

        forecast = demand_forecast.copy()
        if forecast.empty:
            raise ValidationError(
                "Demand forecast cannot be empty when used as a constraint."
            )
        selected_origin: pd.Timestamp | None = None
        if cols.forecast_origin in forecast.columns:
            origins = pd.to_datetime(forecast[cols.forecast_origin], errors="coerce").dt.normalize()
            if origins.isna().any():
                raise ValidationError("Forecast origins must contain valid dates.")
            if as_of is not None:
                selected_origin = pd.Timestamp(as_of).normalize()
                forecast = forecast.loc[origins == selected_origin].copy()
            elif origins.nunique() > 1:
                raise ValidationError(
                    "Forecast contains multiple origins; provide as_of to select one."
                )
            else:
                selected_origin = origins.iloc[0]
        if selected_origin is not None and cols.forecast_date in forecast.columns:
            dates = pd.to_datetime(forecast[cols.forecast_date], errors="coerce").dt.normalize()
            if dates.isna().any():
                raise ValidationError("Forecast dates must contain valid dates.")
            forecast = forecast.loc[
                (dates > selected_origin)
                & (dates <= selected_origin + pd.Timedelta(days=cfg.forecast.horizon_days))
            ].copy()

        forecast_columns = required_forecast.copy()
        if cols.forecast_status in forecast.columns:
            forecast_columns.append(cols.forecast_status)
        forecast = forecast.loc[:, forecast_columns].copy()

        if forecast.empty:
            raise ValidationError(
                "Demand forecast cannot be empty when used as a constraint."
            )

        forecast[cols.sku_id] = forecast[cols.sku_id].astype(str)
        forecast[cols.destination_id] = forecast[
            cols.destination_id
        ].astype(str)

        if cols.forecast_status in forecast.columns:
            forecast = forecast.loc[
                forecast[cols.forecast_status] == "ok"
            ].copy()
        forecast[cols.point_forecast] = pd.to_numeric(
            forecast[cols.point_forecast], errors="coerce"
        )
        values = forecast[cols.point_forecast]
        if values.isna().any() or not values.map(
            lambda x: pd.notna(x) and x >= 0 and abs(float(x)) != float("inf")
        ).all():
            raise ValidationError(
                "Forecast demand must contain finite, non-negative numbers."
            )

        demand_map = (
            forecast.groupby(
                [cols.sku_id, cols.destination_id], sort=False
            )[cols.point_forecast]
            .sum()
            .to_dict()
        )

        for (sku_id, destination_id), group in shipment_rows.groupby(
            [cols.sku_id, cols.destination_id], sort=False
        ):
            demand = demand_map.get((sku_id, destination_id))
            if demand is None:
                raise ValidationError(
                    "No forecast demand exists for an eligible SKU/destination pair.",
                    details={
                        "sku_id": sku_id,
                        "destination_id": destination_id,
                    },
                )

            expression = pulp.lpSum(
                decision_vars[idx] for idx in group.index
            )
            constraint = expression <= float(demand)
            problem += constraint, f"demand_{len(constraints)}"
            constraints.append(constraint)

    return constraints
