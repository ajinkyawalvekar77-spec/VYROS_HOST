
"""Independent verification of Optiqo shipment allocations.

The checker independently verifies that a proposed allocation respects
inventory, eligibility, destination capacity, and forecast-demand limits.
It reports violations instead of silently correcting an invalid plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import math
from collections.abc import Mapping
from datetime import date
import pandas as pd

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from ..schemas import validate_capacities, validate_inventory_batches, validate_lanes


@dataclass
class AllocationCheckResult:
    """Result of independent shipment-plan verification."""

    is_valid: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0
    checks_not_run: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.is_valid:
            return "Allocation is valid. All verification checks passed."
        if self.checks_failed == 0 and self.checks_not_run:
            return (
                "Allocation is not fully verified: "
                f"{len(self.checks_not_run)} required check(s) were not run."
            )
        return (
            f"Allocation is invalid: {self.checks_failed} "
            f"verification check(s) failed."
        )

    def to_frame(self) -> pd.DataFrame:
        """Return all violations as a DataFrame."""
        return pd.DataFrame(
            self.violations,
            columns=["check", "entity", "expected", "actual", "message"],
        )


def verify_allocation(
    plan: pd.DataFrame,
    eligible: pd.DataFrame,
    inventory_batches: pd.DataFrame,
    capacities: pd.DataFrame | None = None,
    demand_forecast: pd.DataFrame | None = None,
    *,
    tolerance: float = 1e-6,
    lanes: pd.DataFrame | None = None,
    as_of: str | date | pd.Timestamp | None = None,
    sku_min_shelf_life_days: Mapping[str, int] | None = None,
    config: EngineConfig | None = None,
) -> AllocationCheckResult:
    """Verify an allocation without modifying the proposed plan.

    Expected plan columns:
        batch_id, sku_id, warehouse_id, destination_id, allocated_quantity

    `eligible` contains the candidate shipment rows used by the optimizer.
    If `eligible_row_id` exists in the plan, it is used to verify that every
    allocation corresponds to a candidate row.

    Returns:
        AllocationCheckResult with validity status and any violations.
    """
    if not isinstance(plan, pd.DataFrame):
        raise TypeError("plan must be a pandas DataFrame.")
    if not isinstance(eligible, pd.DataFrame):
        raise TypeError("eligible must be a pandas DataFrame.")
    if not isinstance(inventory_batches, pd.DataFrame):
        raise TypeError("inventory_batches must be a pandas DataFrame.")

    cfg = config or EngineConfig()
    cols = cfg.columns
    if not math.isfinite(float(tolerance)) or tolerance < 0:
        raise ValueError("tolerance must be a finite non-negative number.")

    required_plan = {
        cols.batch_id,
        cols.sku_id,
        cols.warehouse_id,
        cols.destination_id,
        "allocated_quantity",
    }
    missing_plan = required_plan - set(plan.columns)
    if missing_plan:
        raise SchemaError(
            f"Allocation plan is missing required columns: {sorted(missing_plan)}"
        )

    required_eligible = {
        cols.batch_id,
        cols.sku_id,
        cols.warehouse_id,
        cols.destination_id,
        cols.quantity,
    }
    missing_eligible = required_eligible - set(eligible.columns)
    if missing_eligible:
        raise SchemaError(
            f"Eligible shipments are missing required columns: "
            f"{sorted(missing_eligible)}"
        )

    validated_inventory = validate_inventory_batches(inventory_batches, config=cfg).frame
    inventory = validated_inventory.copy()

    if inventory[cols.batch_id].duplicated().any():
        raise ValidationError(f"Inventory {cols.batch_id} values must be unique.")

    if not plan.empty:
        quantities = pd.to_numeric(
            plan["allocated_quantity"], errors="coerce"
        )
        invalid_quantity = (
            quantities.isna()
            | ~quantities.map(math.isfinite)
            | (quantities < -tolerance)
        )
        if invalid_quantity.any():
            raise ValidationError(
                "allocated_quantity must contain finite, non-negative numbers."
            )

        plan = plan.copy()
        plan["allocated_quantity"] = quantities.clip(lower=0)

    violations: list[dict[str, Any]] = []
    checks_passed = 0
    checks_failed = 0

    def record(
        check: str,
        entity: str,
        expected: Any,
        actual: Any,
        message: str,
        passed: bool,
    ) -> None:
        nonlocal checks_passed, checks_failed
        if passed:
            checks_passed += 1
        else:
            checks_failed += 1
            violations.append(
                {
                    "check": check,
                    "entity": entity,
                    "expected": expected,
                    "actual": actual,
                    "message": message,
                }
            )

    not_run: list[str] = []

    # 1. Every proposed allocation must correspond to an eligible candidate.
    candidate_columns = [
        cols.batch_id,
        cols.sku_id,
        cols.warehouse_id,
        cols.destination_id,
    ]

    if "eligible_row_id" in plan.columns:
        candidate_ids = set(eligible.index)
        candidate_ids_ok = plan["eligible_row_id"].isin(candidate_ids)
        record(
            "eligible_candidate",
            "all_plan_rows",
            "every row references an eligible row",
            int((~candidate_ids_ok).sum()),
            "One or more allocations reference unknown eligible_row_id values.",
            bool(candidate_ids_ok.all()),
        )

        lookup = eligible.copy()
        lookup["_candidate_id"] = lookup.index
        lookup = lookup.set_index("_candidate_id", drop=True)

        identity_ok = candidate_ids_ok.copy()
        for column in candidate_columns:
            expected_values = plan["eligible_row_id"].map(lookup[column])
            identity_ok &= (
                plan[column].astype(str).to_numpy()
                == expected_values.astype(str).to_numpy()
            )

        record(
            "candidate_identity",
            "all_plan_rows",
            "plan identity matches eligible candidate",
            int((~identity_ok).sum()),
            "An allocation's batch, SKU, warehouse, or destination does not "
            "match its referenced eligible candidate.",
            bool(identity_ok.all()),
        )
        candidate_limits = plan["eligible_row_id"].map(lookup[cols.quantity])
        allocated_candidate = plan.assign(
            _candidate_limit=candidate_limits
        ).groupby("eligible_row_id", dropna=False).agg(
            allocated=("allocated_quantity", "sum"),
            candidate_limit=("_candidate_limit", "first"),
        )
        for candidate_id, row in allocated_candidate.iterrows():
            limit = row["candidate_limit"]
            record(
                "candidate_quantity_limit",
                str(candidate_id),
                float(limit) if pd.notna(limit) else "known candidate",
                float(row["allocated"]),
                "Allocated quantity exceeds the eligible candidate quantity.",
                pd.notna(limit) and float(row["allocated"]) <= float(limit) + tolerance,
            )
    else:
        if eligible.duplicated(candidate_columns).any():
            raise ValidationError(
                "Eligible rows contain duplicate shipment keys; include eligible_row_id to disambiguate them."
            )
        candidate_keys = set(
            map(
                tuple,
                eligible[candidate_columns].astype(str).to_numpy(),
            )
        )
        plan_keys = list(
            map(tuple, plan[candidate_columns].astype(str).to_numpy())
        )
        unknown_rows = sum(key not in candidate_keys for key in plan_keys)
        record(
            "eligible_candidate",
            "all_plan_rows",
            "every row matches an eligible candidate",
            unknown_rows,
            "One or more allocations are not present in the eligible shipment set.",
            unknown_rows == 0,
        )
        candidate_limits = {
            tuple(row[column] for column in candidate_columns): float(row[cols.quantity])
            for _, row in eligible.iterrows()
        }
        candidate_allocations = plan.groupby(
            candidate_columns, dropna=False
        )["allocated_quantity"].sum()
        for key, allocated_quantity in candidate_allocations.items():
            if not isinstance(key, tuple):
                key = (key,)
            limit = candidate_limits.get(key)
            record(
                "candidate_quantity_limit",
                str(key),
                limit if limit is not None else "known candidate",
                float(allocated_quantity),
                "Allocated quantity exceeds the eligible candidate quantity.",
                limit is not None and float(allocated_quantity) <= limit + tolerance,
            )

    # 2. Each batch must exist and its total allocated quantity cannot exceed stock.
    inventory_stock = inventory.set_index(cols.batch_id)[cols.quantity]
    allocated_by_batch = plan.groupby(cols.batch_id)["allocated_quantity"].sum()

    unknown_batches = set(plan[cols.batch_id]) - set(inventory_stock.index)
    record(
        "known_inventory_batch",
        "all_plan_rows",
        "all batch IDs exist in inventory",
        len(unknown_batches),
        f"Unknown batch IDs: {sorted(map(str, unknown_batches))}",
        len(unknown_batches) == 0,
    )

    for batch_id, allocated in allocated_by_batch.items():
        if batch_id not in inventory_stock.index:
            continue
        stock = float(inventory_stock.loc[batch_id])
        record(
            "stock_limit",
            str(batch_id),
            stock,
            float(allocated),
            "Allocated quantity exceeds available batch stock.",
            float(allocated) <= stock + tolerance,
        )

    # 3. Batch identity must match the inventory record.
    inventory_lookup = inventory.set_index(cols.batch_id)
    for column in (cols.sku_id, cols.warehouse_id):
        if column not in inventory.columns:
            continue
        known = plan[cols.batch_id].isin(inventory_lookup.index)
        matched = plan.loc[known, column].astype(str).to_numpy() == (
            plan.loc[known, cols.batch_id]
            .map(inventory_lookup[column])
            .astype(str)
            .to_numpy()
        )
        record(
            f"inventory_{column}",
            "all_plan_rows",
            f"{column} matches inventory batch",
            int((~matched).sum()),
            f"Plan {column} differs from the inventory record.",
            bool(matched.all()),
        )

    if lanes is None:
        not_run.append("route availability (lanes were not supplied)")
    else:
        lane_frame = validate_lanes(lanes, config=cfg).frame
        lane_lookup = lane_frame.set_index(
            [cols.warehouse_id, cols.destination_id]
        )[cols.is_available]
        for _, row in plan.iterrows():
            key = (str(row[cols.warehouse_id]), str(row[cols.destination_id]))
            available = bool(lane_lookup.loc[key]) if key in lane_lookup.index else False
            record(
                "available_route",
                str(key),
                True,
                available,
                "Shipment uses a missing or unavailable route.",
                available,
            )

    minimum_life: dict[str, int] | None = None
    if sku_min_shelf_life_days is not None:
        if not isinstance(sku_min_shelf_life_days, Mapping):
            raise TypeError("sku_min_shelf_life_days must be a mapping.")
        minimum_life = {}
        for sku, minimum in sku_min_shelf_life_days.items():
            if (
                isinstance(minimum, bool)
                or not isinstance(minimum, int)
                or minimum < 0
            ):
                raise ValidationError(
                    "SKU minimum shelf-life values must be non-negative integers.",
                    details={"sku_id": str(sku), "value": repr(minimum)},
                )
            minimum_life[str(sku)] = minimum

    if as_of is None or minimum_life is None:
        not_run.append("arrival shelf-life eligibility (as_of date and SKU minimums are required)")
    elif lanes is not None:
        origin = pd.Timestamp(as_of).normalize()
        lane_frame = validate_lanes(lanes, config=cfg).frame
        if cols.transit_days not in lane_frame.columns:
            record(
                "arrival_shelf_life",
                "all_plan_rows",
                "lane transit time is available",
                "missing",
                "Cannot recompute shelf life without lane transit_days.",
                False,
            )
        else:
            lane_transit = lane_frame.set_index(
                [cols.warehouse_id, cols.destination_id]
            )[cols.transit_days]
            for _, row in plan.iterrows():
                if row[cols.batch_id] not in inventory_lookup.index:
                    continue
                batch = inventory_lookup.loc[row[cols.batch_id]]
                sku = str(row[cols.sku_id])
                key = (str(row[cols.warehouse_id]), str(row[cols.destination_id]))
                if key not in lane_transit.index:
                    record("arrival_shelf_life", str(key), "valid lane", "missing", "No lane transit record exists.", False)
                    continue
                if sku not in minimum_life:
                    record("arrival_shelf_life", sku, "minimum shelf-life rule", "missing", "No SKU minimum shelf-life rule exists.", False)
                    continue
                transit = int(lane_transit.loc[key])
                arrival = origin + pd.Timedelta(days=transit)
                if cols.expiry_date in batch.index:
                    life = int((batch[cols.expiry_date] - arrival).days)
                elif cols.remaining_shelf_life_days in batch.index:
                    life = int(batch[cols.remaining_shelf_life_days]) - transit
                else:
                    record("arrival_shelf_life", str(row[cols.batch_id]), "expiry evidence", "missing", "Inventory has no expiry or remaining-life value.", False)
                    continue
                minimum = minimum_life[sku]
                record(
                    "arrival_shelf_life",
                    str(row[cols.batch_id]),
                    minimum,
                    life,
                    "Batch does not meet minimum shelf life at arrival.",
                    life >= minimum,
                )

    # 4. Destination capacity limits.
    if capacities is not None:
        cap_frame = validate_capacities(capacities, config=cfg).frame.copy()
        dimensions = [cols.destination_id]
        dimensions.extend(key for key in (cols.sku_id, cols.warehouse_id) if key in cap_frame.columns)
        if cols.effective_date in cap_frame.columns:
            cap_as_of = pd.Timestamp(as_of).normalize() if as_of is not None else None
            if cap_as_of is None and demand_forecast is not None and cols.forecast_origin in demand_forecast.columns:
                origins = pd.to_datetime(demand_forecast[cols.forecast_origin], errors="coerce").dropna()
                if not origins.empty:
                    cap_as_of = origins.max().normalize()
            if cap_as_of is None:
                raise ValidationError("Effective-dated capacity checking requires as_of or forecast_origin.")
            cap_frame = cap_frame.loc[cap_frame[cols.effective_date] <= cap_as_of].copy()
            if cap_frame.empty:
                raise ValidationError("No capacity record is effective on or before as_of.")
            latest = cap_frame.groupby(dimensions)[cols.effective_date].transform("max")
            cap_frame = cap_frame.loc[cap_frame[cols.effective_date] == latest]
        if cap_frame.duplicated(dimensions).any():
            raise ValidationError(f"Capacity rows are ambiguous at dimensions {dimensions}.")
        if not plan.empty:
            totals = plan.groupby(dimensions, dropna=False)["allocated_quantity"].sum().reset_index()
        else:
            totals = pd.DataFrame(columns=dimensions + ["allocated_quantity"])
        cap_lookup = {
            tuple(row[column] for column in dimensions): float(row[cols.capacity_units])
            for row in cap_frame.to_dict("records")
        }
        for _, row in totals.iterrows():
            key = tuple(row[column] for column in dimensions)
            capacity = cap_lookup.get(key)
            if capacity is None:
                record("capacity_record", str(key), "capacity record", "missing", "No capacity record exists for this allocation group.", False)
                continue
            allocated = float(row["allocated_quantity"])
            record("capacity_limit", str(key), capacity, allocated, "Allocated quantity exceeds applicable capacity.", allocated <= capacity + tolerance)

    # 5. Forecast-demand limits, grouped by SKU and destination.
    if demand_forecast is not None:
        required_demand = {cols.sku_id, cols.destination_id, cols.point_forecast}
        missing_demand = required_demand - set(demand_forecast.columns)
        if missing_demand:
            raise SchemaError(
                f"Demand forecast is missing required columns: "
                f"{sorted(missing_demand)}"
            )

        forecast_source = demand_forecast.copy()
        if forecast_source.empty:
            raise ValidationError("Demand forecast cannot be empty when checking allocated demand.")
        selected_origin: pd.Timestamp | None = None
        if cols.forecast_origin in forecast_source.columns:
            origins = pd.to_datetime(
                forecast_source[cols.forecast_origin], errors="coerce"
            ).dt.normalize()
            if origins.isna().any():
                raise ValidationError("Forecast origins must contain valid dates.")
            if as_of is not None:
                selected_origin = pd.Timestamp(as_of).normalize()
                forecast_source = forecast_source.loc[origins == selected_origin].copy()
            elif origins.nunique() > 1:
                raise ValidationError(
                    "Forecast contains multiple origins; provide as_of to verify demand limits."
                )
            else:
                selected_origin = origins.iloc[0]
        if selected_origin is not None and cols.forecast_date in forecast_source.columns:
            dates = pd.to_datetime(
                forecast_source[cols.forecast_date], errors="coerce"
            ).dt.normalize()
            if dates.isna().any():
                raise ValidationError("Forecast dates must contain valid dates.")
            forecast_source = forecast_source.loc[
                (dates > selected_origin)
                & (dates <= selected_origin + pd.Timedelta(days=cfg.forecast.horizon_days))
            ].copy()
        demand = forecast_source[
            [cols.sku_id, cols.destination_id, cols.point_forecast]
        ].copy()
        if cols.forecast_status in forecast_source.columns:
            demand = demand.loc[
                forecast_source[cols.forecast_status] == "ok"
            ].copy()
        demand[cols.point_forecast] = pd.to_numeric(
            demand[cols.point_forecast], errors="coerce"
        )
        if (
            demand[cols.point_forecast].isna().any()
            or (~demand[cols.point_forecast].map(math.isfinite)).any()
            or (demand[cols.point_forecast] < 0).any()
        ):
            raise ValidationError(
                "point_forecast must contain finite, non-negative values."
            )

        demand = demand.groupby(
            [cols.sku_id, cols.destination_id], as_index=False
        )[cols.point_forecast].sum()

        allocated = plan.groupby(
            [cols.sku_id, cols.destination_id], as_index=False
        )["allocated_quantity"].sum()

        demand_lookup = demand.set_index(
            [cols.sku_id, cols.destination_id]
        )[cols.point_forecast]

        for _, row in allocated.iterrows():
            key = (row[cols.sku_id], row[cols.destination_id])
            quantity = float(row["allocated_quantity"])

            if key not in demand_lookup.index:
                record(
                    "forecast_record",
                    str(key),
                    "a demand forecast exists",
                    quantity,
                    "No demand forecast exists for this SKU/destination.",
                    False,
                )
                continue

            forecast = float(demand_lookup.loc[key])
            record(
                "forecast_demand_limit",
                str(key),
                forecast,
                quantity,
                "Allocated quantity exceeds forecast demand.",
                quantity <= forecast + tolerance,
            )

    return AllocationCheckResult(
        is_valid=(checks_failed == 0 and not not_run),
        violations=violations,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        checks_not_run=not_run,
    )
