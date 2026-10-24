"""Dataset validation using the engine validators plus cross-table references."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

import pandas as pd
import numpy as np

from .engine_adapter import _load_engine, frame_from_rows, json_safe
from .schemas import DatasetPayload, Finding, TableValidation, ValidationReport


TABLE_FIELDS = {
    "demand_history": {
        "required": {"sku_id", "destination_id", "demand_date", "quantity"},
        "optional": set(),
        "validator": "validate_demand",
    },
    "inventory_batches": {
        "required": {"batch_id", "sku_id", "warehouse_id", "quantity"},
        "optional": {"expiry_date", "received_date", "remaining_shelf_life_days"},
        "validator": "validate_inventory_batches",
    },
    "lanes": {
        "required": {"warehouse_id", "destination_id", "is_available"},
        "optional": {"transit_days"},
        "validator": "validate_lanes",
    },
    "transport_costs": {
        "required": {"warehouse_id", "destination_id", "unit_transport_cost"},
        "optional": {"sku_id"},
        "validator": "validate_transport_costs",
    },
    "capacities": {
        "required": {"destination_id", "capacity_units"},
        "optional": {"sku_id", "warehouse_id", "effective_date"},
        "validator": "validate_capacities",
    },
}


def _is_missing_scalar(value: Any) -> bool:
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def _add_engine_error(
    findings: list[Finding], table: str, frame: pd.DataFrame, exc: Exception
) -> None:
    details = getattr(exc, "details", {})
    detail_map = details if isinstance(details, dict) else {"details": details}
    row_indices: list[int] = []
    for key in (
        "invalid_index_sample",
        "null_row_index_sample",
        "negative_index_sample",
        "empty_index_sample",
        "zero_index_sample",
    ):
        sample = detail_map.get(key)
        if isinstance(sample, list):
            row_indices.extend(
                int(index) for index in sample if isinstance(index, int)
            )
    if row_indices:
        for row_index in sorted(set(row_indices)):
            findings.append(
                Finding(
                    table=table,
                    row=row_index,
                    field=detail_map.get("column"),
                    rule=type(exc).__name__,
                    message=str(exc),
                    details=json_safe(detail_map),
                )
            )
        return
    duplicate_keys = detail_map.get("duplicate_key_sample")
    key_columns = detail_map.get("key_columns")
    if isinstance(duplicate_keys, list) and isinstance(key_columns, list):
        matching_rows: set[int] = set()
        if all(column in frame for column in key_columns):
            for key_values in duplicate_keys:
                mask = pd.Series(True, index=frame.index)
                for column in key_columns:
                    if column not in key_values:
                        mask &= False
                    else:
                        mask &= frame[column].eq(key_values[column])
                matching_rows.update(int(index) for index in frame.index[mask])
        if matching_rows:
            for row_index in sorted(matching_rows):
                findings.append(
                    Finding(
                        table=table,
                        row=row_index,
                        rule=type(exc).__name__,
                        message=str(exc),
                        details=json_safe(detail_map),
                    )
                )
            return
    findings.append(
        Finding(
            table=table,
            field=detail_map.get("column"),
            rule=type(exc).__name__,
            message=str(exc),
            details=json_safe(detail_map),
        )
    )


def validate_dataset(
    payload: DatasetPayload,
    *,
    scope: str = "full_network",
) -> ValidationReport:
    if scope not in {"demand_only", "full_network"}:
        raise ValueError("Validation scope must be 'demand_only' or 'full_network'.")
    engine = _load_engine()
    findings: list[Finding] = []
    tables: dict[str, TableValidation] = {}
    frames: dict[str, pd.DataFrame] = {}

    table_fields = (
        {"demand_history": TABLE_FIELDS["demand_history"]}
        if scope == "demand_only"
        else TABLE_FIELDS
    )
    for table, info in table_fields.items():
        records = getattr(payload, table)
        frame = frame_from_rows(records)
        frames[table] = frame
        row_error_start = len(findings)
        if frame.empty:
            findings.append(
                Finding(
                    table=table,
                    rule="required_table",
                    message="At least one record is required for this dataset table.",
                )
            )
            tables[table] = TableValidation(valid=False, row_count=0)
            continue

        missing_columns = sorted(info["required"] - set(frame.columns))
        if missing_columns:
            findings.append(
                Finding(
                    table=table,
                    rule="required_columns",
                    message="Required columns are missing.",
                    details={"missing_columns": missing_columns},
                )
            )
        unsupported = sorted(
            set(frame.columns) - info["required"] - info["optional"]
        )
        if unsupported:
            findings.append(
                Finding(
                    table=table,
                    rule="unsupported_columns",
                    message="Columns are not part of the current engine contract.",
                    details={"unsupported_columns": unsupported},
                )
            )
        _preflight_table(table, frame, info, payload.as_of, findings)
        if table == "demand_history":
            _check_demand_gaps(frame, findings)
        validator: Callable[..., Any] = engine[info["validator"]]
        if not any(
            finding.table == table and finding.severity == "error"
            for finding in findings
        ):
            try:
                validator(frame)
            except Exception as exc:
                _add_engine_error(findings, table, frame, exc)
        tables[table] = TableValidation(
            valid=len(findings) == row_error_start,
            row_count=len(frame),
        )

    if scope == "full_network":
        _check_references(frames, payload.sku_min_shelf_life_days, findings)
        _validate_warehouse_receipts(
            payload.warehouse_receipts, frames["inventory_batches"], findings
        )
        if payload.warehouse_receipts:
            tables["warehouse_receipts"] = TableValidation(
                valid=not any(
                    finding.table == "warehouse_receipts"
                    and finding.severity == "error"
                    for finding in findings
                ),
                row_count=len(payload.warehouse_receipts),
            )
    for table in tables:
        tables[table].valid = not any(
            finding.table == table and finding.severity == "error"
            for finding in findings
        )
    error_count = sum(finding.severity == "error" for finding in findings)
    warning_count = sum(finding.severity == "warning" for finding in findings)
    return ValidationReport(
        validation_scope=scope,
        valid=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        tables=tables,
        findings=findings,
    )


def _check_demand_gaps(frame: pd.DataFrame, findings: list[Finding]) -> None:
    required = {"sku_id", "destination_id", "demand_date"}
    if not required.issubset(frame.columns) or frame.empty:
        return
    dates = pd.to_datetime(frame["demand_date"], errors="coerce")
    if dates.isna().any():
        return
    demand = frame.assign(_parsed_date=dates.dt.normalize())
    for (sku_id, destination_id), series in demand.groupby(
        ["sku_id", "destination_id"], dropna=False
    ):
        observed = pd.DatetimeIndex(sorted(series["_parsed_date"].unique()))
        if len(observed) < 2:
            continue
        expected = pd.date_range(observed.min(), observed.max(), freq="D")
        gaps = expected.difference(observed)
        if len(gaps):
            findings.append(
                Finding(
                    severity="warning",
                    table="demand_history",
                    field="demand_date",
                    rule="missing_daily_observations",
                    message="Demand history has calendar-date gaps; values were not imputed.",
                    details={
                        "sku_id": str(sku_id),
                        "destination_id": str(destination_id),
                        "missing_date_count": len(gaps),
                        "missing_dates_sample": [day.date().isoformat() for day in gaps[:10]],
                    },
                )
            )


def _preflight_table(
    table: str,
    frame: pd.DataFrame,
    info: dict[str, Any],
    as_of: Any,
    findings: list[Finding],
) -> None:
    present_columns = set(frame.columns)
    id_columns = {
        "demand_history": ("sku_id", "destination_id"),
        "inventory_batches": ("batch_id", "sku_id", "warehouse_id"),
        "lanes": ("warehouse_id", "destination_id"),
        "transport_costs": ("warehouse_id", "destination_id", "sku_id"),
        "capacities": ("destination_id", "sku_id", "warehouse_id"),
    }[table]
    date_columns = {
        "demand_history": ("demand_date",),
        "inventory_batches": ("expiry_date", "received_date"),
        "lanes": (),
        "transport_costs": (),
        "capacities": ("effective_date",),
    }[table]
    for column in sorted(info["required"] & present_columns):
        missing = frame[column].isna()
        for index in frame.index[missing]:
            findings.append(
                Finding(
                    table=table,
                    row=int(index),
                    field=column,
                    rule="missing_value",
                    message="Required values cannot be missing.",
                )
            )
    for column in sorted(info["optional"] & present_columns):
        missing = frame[column].isna()
        for index in frame.index[missing]:
            findings.append(
                Finding(
                    table=table,
                    row=int(index),
                    field=column,
                    rule="missing_value",
                    message="A supplied optional field cannot contain missing values.",
                )
            )
    for column in id_columns:
        if column not in frame:
            continue
        invalid = frame[column].map(
            lambda value: not _is_missing_scalar(value)
            and (not str(value).strip() or str(value).strip().lower() == "nan")
        )
        for index in frame.index[invalid]:
            findings.append(
                Finding(
                    table=table,
                    row=int(index),
                    field=column,
                    rule="empty_identifier",
                    message="Identifier values cannot be empty.",
                )
            )
    for column in date_columns:
        if column not in frame:
            continue
        for index, value in frame[column].items():
            if _is_missing_scalar(value):
                continue
            if not isinstance(value, (str, date, datetime, pd.Timestamp)):
                parsed = None
            else:
                try:
                    parsed = pd.to_datetime(value, errors="coerce")
                except (TypeError, ValueError):
                    parsed = None
            if parsed is None or pd.isna(parsed):
                findings.append(
                    Finding(
                        table=table,
                        row=int(index),
                        field=column,
                        rule="invalid_date",
                        message="Date must be a valid date string or date value.",
                        details={"value": json_safe(value)},
                    )
                )
        if table == "inventory_batches" and column == "expiry_date" and as_of:
            parsed_dates = pd.Series(
                [
                    pd.to_datetime(value, errors="coerce")
                    if isinstance(value, (str, date, datetime, pd.Timestamp))
                    else pd.NaT
                    for value in frame[column]
                ],
                index=frame.index,
            )
            expired = parsed_dates.dt.normalize() < pd.Timestamp(as_of).normalize()
            for index in frame.index[expired.fillna(False)]:
                findings.append(
                    Finding(
                        table=table,
                        row=int(index),
                        field=column,
                        rule="expired_batch",
                        message="Batch expiry precedes the supplied planning date.",
                        details={"as_of": str(as_of), "expiry_date": str(frame.at[index, column])},
                    )
                )

    numeric_columns: dict[str, dict[str, tuple[bool, float | None]]] = {
        "demand_history": {"quantity": (False, 0)},
        "inventory_batches": {
            "quantity": (False, 0),
            "remaining_shelf_life_days": (True, 0),
        },
        "lanes": {"transit_days": (True, 1)},
        "transport_costs": {"unit_transport_cost": (False, 0)},
        "capacities": {"capacity_units": (False, 0)},
    }[table]
    for column, (whole_number, minimum) in numeric_columns.items():
        if column not in frame:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        invalid = values.isna() | ~values.map(
            lambda value: pd.notna(value) and abs(float(value)) != float("inf")
        )
        for index in frame.index[invalid]:
            findings.append(
                Finding(
                    table=table,
                    row=int(index),
                    field=column,
                    rule="invalid_numeric",
                    message="Value must be numeric and finite.",
                    details={"value": json_safe(frame.at[index, column])},
                )
            )
        finite = values.loc[~invalid]
        if minimum is not None:
            below = (
                finite <= minimum
                if column == "capacity_units"
                else finite < minimum
            )
            for index in finite.index[below]:
                findings.append(
                    Finding(
                        table=table,
                        row=int(index),
                        field=column,
                        rule="below_minimum",
                        message=(
                            "Transit days must be at least one."
                            if column == "transit_days"
                            else "Capacity must be positive."
                            if column == "capacity_units"
                            else "Value cannot be negative."
                        ),
                        details={"value": json_safe(values.at[index]), "minimum": minimum},
                    )
                )
        if whole_number:
            fractional = finite % 1 != 0
            for index in finite.index[fractional]:
                findings.append(
                    Finding(
                        table=table,
                        row=int(index),
                        field=column,
                        rule="whole_number",
                        message="Value must be a whole number.",
                        details={"value": json_safe(values.at[index])},
                    )
                )

    if table == "lanes" and "is_available" in frame:
        allowed = {True, False, 1, 0, "true", "false", "True", "False", "1", "0"}
        for index, value in frame["is_available"].items():
            try:
                valid = value in allowed
            except TypeError:
                valid = False
            if not valid:
                findings.append(
                    Finding(
                        table=table,
                        row=int(index),
                        field="is_available",
                        rule="invalid_boolean",
                        message="Lane availability must be boolean or an accepted true/false value.",
                        details={"value": json_safe(value)},
                    )
                )

    business_keys = {
        "demand_history": ["sku_id", "destination_id", "demand_date"],
        "inventory_batches": ["batch_id"],
        "lanes": ["warehouse_id", "destination_id"],
        "transport_costs": ["warehouse_id", "destination_id"]
        + (["sku_id"] if "sku_id" in frame else []),
        "capacities": ["destination_id"]
        + [key for key in ("sku_id", "warehouse_id", "effective_date") if key in frame],
    }[table]
    if set(business_keys).issubset(frame.columns):
        duplicate_rows = frame.duplicated(subset=business_keys, keep=False)
        for index in frame.index[duplicate_rows]:
            findings.append(
                Finding(
                    table=table,
                    row=int(index),
                    rule="duplicate_key",
                    message="Business key must be unique.",
                    details={
                        "key_columns": business_keys,
                        "key": json_safe(frame.loc[index, business_keys].to_dict()),
                    },
                )
            )


def _check_references(
    frames: dict[str, pd.DataFrame],
    minimum_shelf_life: dict[str, int],
    findings: list[Finding],
) -> None:
    demand = frames["demand_history"]
    inventory = frames["inventory_batches"]
    lanes = frames["lanes"]
    costs = frames["transport_costs"]
    capacities = frames["capacities"]

    def unknown_reference(
        table: str,
        column: str,
        known: set[Any],
        reference_label: str,
    ) -> None:
        frame = frames[table]
        if column not in frame or not known:
            return
        values = frame[column]
        unknown = values.notna() & ~values.map(
            lambda value: str(value) in known
            if not _is_missing_scalar(value)
            else True
        )
        for index in frame.index[unknown][:100]:
            findings.append(
                Finding(
                    table=table,
                    row=int(index),
                    field=column,
                    rule="unknown_reference",
                    message=f"{column} does not reference a known {reference_label}.",
                    details={"value": json_safe(frame.at[index, column])},
                )
            )

    demand_skus = (
        set(demand["sku_id"].dropna().map(str))
        if "sku_id" in demand
        else set()
    )
    demand_destinations = (
        set(demand["destination_id"].dropna().map(str))
        if "destination_id" in demand
        else set()
    )
    inventory_skus = (
        set(inventory["sku_id"].dropna().map(str))
        if "sku_id" in inventory
        else set()
    )
    inventory_warehouses = (
        set(inventory["warehouse_id"].dropna().map(str))
        if "warehouse_id" in inventory
        else set()
    )
    lane_warehouses = (
        set(lanes["warehouse_id"].dropna().map(str))
        if "warehouse_id" in lanes
        else set()
    )
    lane_destinations = (
        set(lanes["destination_id"].dropna().map(str))
        if "destination_id" in lanes
        else set()
    )

    unknown_reference("inventory_batches", "sku_id", demand_skus, "demand SKU")
    unknown_reference(
        "inventory_batches", "warehouse_id", lane_warehouses, "lane warehouse"
    )
    unknown_reference("lanes", "destination_id", demand_destinations, "destination")
    unknown_reference("lanes", "warehouse_id", inventory_warehouses, "warehouse")
    unknown_reference("transport_costs", "warehouse_id", lane_warehouses, "lane")
    unknown_reference("transport_costs", "destination_id", lane_destinations, "lane")
    if "sku_id" in costs:
        unknown_reference("transport_costs", "sku_id", inventory_skus, "inventory SKU")
    unknown_reference(
        "capacities", "destination_id", demand_destinations, "destination"
    )
    if "sku_id" in capacities:
        unknown_reference("capacities", "sku_id", inventory_skus, "inventory SKU")
    if "warehouse_id" in capacities:
        unknown_reference(
            "capacities", "warehouse_id", inventory_warehouses, "warehouse"
        )
    missing_minimums = sorted(inventory_skus - set(minimum_shelf_life))
    for sku in missing_minimums:
        findings.append(
            Finding(
                table="sku_min_shelf_life_days",
                field=sku,
                rule="missing_shelf_life_requirement",
                message="Every inventory SKU requires a minimum shelf-life value.",
                details={"sku_id": sku},
            )
        )
    for sku, days in minimum_shelf_life.items():
        if days < 0:
            findings.append(
                Finding(
                    table="sku_min_shelf_life_days",
                    field=sku,
                    rule="non_negative_shelf_life",
                    message="Minimum shelf life cannot be negative.",
                    details={"value": days},
                )
            )
        elif sku not in inventory_skus:
            findings.append(
                Finding(
                    table="sku_min_shelf_life_days",
                    field=sku,
                    rule="unknown_sku_requirement",
                    message="Shelf-life mapping references an SKU absent from inventory.",
                    details={"sku_id": sku},
                )
            )

    if {"warehouse_id", "destination_id"}.issubset(costs.columns) and {
        "warehouse_id",
        "destination_id",
    }.issubset(lanes.columns):
        lane_keys = set(
            zip(lanes["warehouse_id"].astype(str), lanes["destination_id"].astype(str))
        )
        for index, row in costs.iterrows():
            key = (str(row["warehouse_id"]), str(row["destination_id"]))
            if key not in lane_keys:
                findings.append(
                    Finding(
                        table="transport_costs",
                        row=int(index),
                        rule="cost_without_lane",
                        message="Transport cost references a warehouse-destination pair with no lane.",
                        details={"warehouse_id": key[0], "destination_id": key[1]},
                    )
                )


def _validate_warehouse_receipts(
    receipts: list[dict[str, Any]],
    inventory: pd.DataFrame,
    findings: list[Finding],
) -> None:
    if not receipts:
        return
    frame = frame_from_rows(receipts)
    required = {
        "receipt_id",
        "batch_id",
        "sku_id",
        "warehouse_id",
        "quantity",
        "arrival_date",
        "expiry_date",
    }
    for column in sorted(required - set(frame.columns)):
        findings.append(
                Finding(
                    table="warehouse_receipts",
                    field=column,
                    rule="required_column",
                    message="Warehouse receipt field is required.",
                )
        )
    for column in required & set(frame.columns):
        missing = frame[column].isna()
        for index in frame.index[missing]:
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field=column,
                        rule="missing_value",
                        message="Receipt values cannot be missing.",
                    )
                )
    for column in ("receipt_id", "batch_id", "sku_id", "warehouse_id"):
        if column not in frame:
                continue
        empty = frame[column].map(
                lambda value: not _is_missing_scalar(value) and not str(value).strip()
        )
        for index in frame.index[empty]:
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field=column,
                        rule="empty_identifier",
                        message="Receipt identifiers cannot be empty.",
                    )
                )
    for column in ("arrival_date", "expiry_date"):
        if column not in frame:
                continue
        parsed = pd.to_datetime(frame[column], errors="coerce")
        for index in frame.index[parsed.isna()]:
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field=column,
                        rule="invalid_date",
                        message="Receipt date must be valid.",
                        details={"value": json_safe(frame.at[index, column])},
                    )
                )
    if "quantity" in frame:
        values = pd.to_numeric(frame["quantity"], errors="coerce")
        invalid = values.isna() | ~values.map(
                lambda value: pd.notna(value) and abs(float(value)) != float("inf")
        )
        for index in frame.index[invalid]:
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field="quantity",
                        rule="invalid_numeric",
                        message="Receipt quantity must be numeric and finite.",
                        details={"value": json_safe(frame.at[index, "quantity"])},
                    )
                )
        for index in values.index[~invalid & (values <= 0)]:
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field="quantity",
                        rule="below_minimum",
                        message="Receipt quantity must be positive.",
                        details={"value": float(values.at[index])},
                    )
                )
    for key in ("receipt_id", "batch_id"):
        if key not in frame:
                continue
        duplicate = frame[key].duplicated(keep=False)
        for index in frame.index[duplicate]:
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field=key,
                        rule="duplicate_key",
                        message=f"Receipt {key} values must be unique.",
                        details={"value": str(frame.at[index, key])},
                    )
                )
    if "batch_id" in frame and "batch_id" in inventory:
        inventory_batch_ids = set(inventory["batch_id"].dropna().map(str))
        for index, value in frame["batch_id"].items():
                if str(value) in inventory_batch_ids:
                    findings.append(
                        Finding(
                            table="warehouse_receipts",
                            row=int(index),
                            field="batch_id",
                            rule="duplicate_batch_id",
                            message="Receipt batch ID duplicates an initial inventory batch.",
                            details={"batch_id": str(value)},
                        )
                    )
    for index, row in frame.iterrows():
        if not {"arrival_date", "expiry_date"}.issubset(frame.columns):
                break
        arrival = pd.to_datetime(row["arrival_date"], errors="coerce")
        expiry = pd.to_datetime(row["expiry_date"], errors="coerce")
        if pd.notna(arrival) and pd.notna(expiry) and expiry.normalize() <= arrival.normalize():
                findings.append(
                    Finding(
                        table="warehouse_receipts",
                        row=int(index),
                        field="expiry_date",
                        rule="expiry_before_usable",
                        message="Receipt expiry must be after its arrival date.",
                    )
                )
    for table_column, known in (
        ("sku_id", set(inventory.get("sku_id", pd.Series(dtype=str)).dropna().map(str))),
        (
                "warehouse_id",
                set(inventory.get("warehouse_id", pd.Series(dtype=str)).dropna().map(str)),
        ),
    ):
        if table_column not in frame:
                continue
        for index, value in frame[table_column].items():
                if not _is_missing_scalar(value) and str(value) not in known:
                    findings.append(
                        Finding(
                            table="warehouse_receipts",
                            row=int(index),
                            field=table_column,
                            rule="unknown_reference",
                            message=f"Receipt references an unknown inventory {table_column}.",
                            details={"value": json_safe(value)},
                        )
                    )
