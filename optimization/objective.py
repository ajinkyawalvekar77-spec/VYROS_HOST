"""Objective function for Optiqo's inventory allocation optimizer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd
import pulp

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from ..schemas import validate_transport_costs


def build_objective(
    problem: pulp.LpProblem,
    decision_vars: Mapping[Any, pulp.LpVariable],
    eligible: pd.DataFrame,
    transport_costs: pd.DataFrame | None = None,
    *,
    config: EngineConfig | None = None,
) -> pulp.LpAffineExpression:
    """Minimize total lane freight cost for a fixed service level.

    Service is optimized lexicographically by ``optimize_allocation`` before
    this freight-cost objective is applied. Costs are currency per quantity
    unit; no synthetic reward or undocumented penalty coefficient is used.
    """

    if not isinstance(problem, pulp.LpProblem):
        raise TypeError("problem must be a PuLP LpProblem.")

    if not isinstance(eligible, pd.DataFrame):
        raise TypeError("eligible must be a pandas DataFrame.")

    if not isinstance(decision_vars, Mapping):
        raise TypeError("decision_vars must be a mapping of row IDs to variables.")

    cfg = config or EngineConfig()
    cols = cfg.columns
    required = {cols.warehouse_id, cols.destination_id, cols.quantity}
    missing = required.difference(eligible.columns)

    if missing:
        raise SchemaError(
            "Eligible shipments are missing objective columns.",
            details={"missing_columns": sorted(missing)},
        )

    if eligible.empty:
        raise ValidationError("Cannot optimize an empty eligible-shipment frame.")

    if not eligible.index.is_unique:
        raise ValidationError("Eligible shipment index must be unique.")

    if set(decision_vars.keys()) != set(eligible.index):
        raise ValidationError(
            "Decision-variable keys must match eligible shipment row IDs."
        )

    quantities = pd.to_numeric(eligible[cols.quantity], errors="coerce")

    if (
        quantities.isna().any()
        or (~quantities.map(lambda value: pd.notna(value) and value >= 0 and pd.api.types.is_number(value) and abs(float(value)) != float("inf"))).any()
    ):
        raise ValidationError(
            "Eligible shipment quantities must be numeric and non-negative."
        )

    costs_by_key: dict[tuple[str, ...], float] = {}
    sku_level = False

    if transport_costs is not None:
        validated = validate_transport_costs(
            transport_costs,
            config=cfg,
        ).frame

        sku_level = cols.sku_id in validated.columns

        for row in validated.to_dict("records"):
            if sku_level:
                key = (
                    str(row[cols.warehouse_id]),
                    str(row[cols.destination_id]),
                    str(row[cols.sku_id]),
                )
            else:
                key = (
                    str(row[cols.warehouse_id]),
                    str(row[cols.destination_id]),
                )

            cost = float(row[cols.unit_transport_cost])
            costs_by_key[key] = cost

    terms = []

    for row_id, row in eligible.iterrows():
        variable = decision_vars[row_id]

        if not isinstance(variable, pulp.LpVariable):
            raise TypeError(
                f"Decision variable for row {row_id!r} is not an LpVariable."
            )

        warehouse = str(row[cols.warehouse_id])
        destination = str(row[cols.destination_id])

        if transport_costs is None:
            unit_cost = 0.0
        elif cols.sku_id in eligible.columns and sku_level:
            key = (warehouse, destination, str(row[cols.sku_id]))
            if key not in costs_by_key:
                raise ValidationError(
                    "Missing transport cost for an eligible SKU and lane.",
                    details={"cost_key": key},
                )
            unit_cost = costs_by_key[key]
        else:
            key = (warehouse, destination)
            if key not in costs_by_key:
                raise ValidationError(
                    "Missing transport cost for an eligible lane.",
                    details={"cost_key": key},
                )
            unit_cost = costs_by_key[key]

        terms.append(unit_cost * variable)

    objective = pulp.lpSum(terms)
    problem.objective = objective
    problem.sense = pulp.LpMinimize

    return objective