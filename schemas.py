"""Proposed input/output schemas and strict validation.

Column names are configurable via ``EngineConfig.columns``. Invalid stock,
negative demand, unparseable dates, and duplicates raise errors. Values are
never clipped, filled, or otherwise converted into valid data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, Mapping

import pandas as pd

from .config import ColumnMap, EngineConfig
from .exceptions import SchemaError, ValidationError


class ForecastStatus(str, Enum):
    OK = "ok"
    INSUFFICIENT_HISTORY = "insufficient_history"
    PREDICTION_FAILED = "prediction_failed"
    NOT_IMPLEMENTED = "not_implemented"


class DataDomain(str, Enum):
    """Keep raw demand, forecasts, and optimization inputs conceptually separate."""

    RAW_DEMAND = "raw_demand"
    INVENTORY_BATCHES = "inventory_batches"
    LANES = "lanes"
    TRANSPORT_COSTS = "transport_costs"
    CAPACITIES = "capacities"
    FORECAST = "forecast"


@dataclass(frozen=True)
class ValidatedFrame:
    domain: DataDomain
    frame: pd.DataFrame
    row_count: int
    notes: tuple[str, ...] = ()


def _cfg(config: EngineConfig | None) -> EngineConfig:
    return config if config is not None else EngineConfig()


def _require_dataframe(frame: pd.DataFrame, *, domain: DataDomain) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise SchemaError(
            "Expected a pandas DataFrame.",
            details={"domain": domain.value, "received_type": type(frame).__name__},
        )


def _require_columns(
    frame: pd.DataFrame,
    required: Iterable[str],
    *,
    domain: DataDomain,
) -> None:
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise SchemaError(
            "Frame is missing required columns.",
            details={
                "domain": domain.value,
                "missing_columns": missing,
                "present_columns": list(frame.columns),
            },
        )


def _reject_nulls(
    frame: pd.DataFrame,
    columns: Iterable[str],
    *,
    domain: DataDomain,
) -> None:
    for column in columns:
        null_mask = frame[column].isna()
        if bool(null_mask.any()):
            sample_index = frame.index[null_mask].tolist()[:10]
            raise ValidationError(
                f"Column {column!r} contains missing values.",
                details={
                    "domain": domain.value,
                    "column": column,
                    "null_row_index_sample": sample_index,
                    "null_count": int(null_mask.sum()),
                },
            )


def _parse_date_series(series: pd.Series, *, column: str, domain: DataDomain) -> pd.Series:
    """Parse dates without inventing values. Fail the frame if any value is invalid."""
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="raise")
        return parsed.dt.normalize()
    if len(series) == 0:
        return pd.to_datetime(series)

    invalid_positions: list[Any] = []
    converted: list[pd.Timestamp] = []
    for idx, value in series.items():
        if isinstance(value, datetime):
            converted.append(pd.Timestamp(value).normalize())
            continue
        if isinstance(value, date) and not isinstance(value, datetime):
            converted.append(pd.Timestamp(value))
            continue
        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                invalid_positions.append(idx)
                continue
            converted.append(value.normalize())
            continue
        if isinstance(value, str):
            try:
                converted.append(pd.Timestamp(value).normalize())
            except (TypeError, ValueError):
                invalid_positions.append(idx)
            continue
        invalid_positions.append(idx)

    if invalid_positions:
        raise ValidationError(
            f"Column {column!r} contains unparseable or missing dates.",
            details={
                "domain": domain.value,
                "column": column,
                "invalid_index_sample": invalid_positions[:10],
                "invalid_count": len(invalid_positions),
            },
        )
    return pd.Series(converted, index=series.index, dtype="datetime64[ns]")


def _require_numeric_non_negative(
    series: pd.Series,
    *,
    column: str,
    domain: DataDomain,
    allow_zero: bool = True,
    integer_like: bool = False,
) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    unparseable = numeric.isna() & series.notna()
    if bool(unparseable.any()) or bool(numeric.isna().any()):
        bad = series.index[numeric.isna()].tolist()[:10]
        raise ValidationError(
            f"Column {column!r} contains non-numeric or missing values.",
            details={"domain": domain.value, "column": column, "invalid_index_sample": bad},
        )
    if bool((numeric < 0).any()):
        bad = series.index[numeric < 0].tolist()[:10]
        raise ValidationError(
            f"Column {column!r} contains negative values. Values are not clipped.",
            details={
                "domain": domain.value,
                "column": column,
                "negative_index_sample": bad,
                "negative_count": int((numeric < 0).sum()),
            },
        )
    finite = numeric.map(lambda value: pd.notna(value) and abs(float(value)) != float("inf"))
    if not bool(finite.all()):
        bad = series.index[~finite].tolist()[:10]
        raise ValidationError(
            f"Column {column!r} contains non-finite values.",
            details={"domain": domain.value, "column": column, "invalid_index_sample": bad},
        )
    if not allow_zero and bool((numeric == 0).any()):
        bad = series.index[numeric == 0].tolist()[:10]
        raise ValidationError(
            f"Column {column!r} contains zeros where a positive value is required.",
            details={"domain": domain.value, "column": column, "zero_index_sample": bad},
        )
    if integer_like:
        if bool((numeric % 1 != 0).any()):
            bad = series.index[numeric % 1 != 0].tolist()[:10]
            raise ValidationError(
                f"Column {column!r} must be whole numbers.",
                details={"domain": domain.value, "column": column, "non_integer_index_sample": bad},
            )
        return numeric.astype("int64")
    return numeric.astype("float64")


def _assert_unique(
    frame: pd.DataFrame,
    keys: list[str],
    *,
    domain: DataDomain,
) -> None:
    duplicated = frame.duplicated(subset=keys, keep=False)
    if bool(duplicated.any()):
        sample = frame.loc[duplicated, keys].head(10).to_dict(orient="records")
        raise ValidationError(
            "Duplicate records are not allowed.",
            details={
                "domain": domain.value,
                "key_columns": keys,
                "duplicate_count": int(duplicated.sum()),
                "duplicate_key_sample": sample,
            },
        )


def _stringify_ids(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        out[column] = out[column].astype(str).str.strip()
        empty = out[column].eq("") | out[column].str.lower().eq("nan")
        if bool(empty.any()):
            raise ValidationError(
                f"Column {column!r} contains empty identifiers.",
                details={"column": column, "empty_index_sample": out.index[empty].tolist()[:10]},
            )
    return out


def validate_demand(
    frame: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> ValidatedFrame:
    """Validate historical demand. Zero demand is allowed; negatives are not."""
    cfg = _cfg(config)
    cols = cfg.columns
    domain = DataDomain.RAW_DEMAND
    _require_dataframe(frame, domain=domain)
    required = [cols.sku_id, cols.destination_id, cols.demand_date, cols.quantity]
    _require_columns(frame, required, domain=domain)
    out = frame.loc[:, required].copy()
    _reject_nulls(out, required, domain=domain)
    out = _stringify_ids(out, [cols.sku_id, cols.destination_id])
    out[cols.demand_date] = _parse_date_series(out[cols.demand_date], column=cols.demand_date, domain=domain)
    out[cols.quantity] = _require_numeric_non_negative(
        out[cols.quantity], column=cols.quantity, domain=domain, allow_zero=True
    )
    _assert_unique(out, [cols.sku_id, cols.destination_id, cols.demand_date], domain=domain)
    notes: list[str] = []
    if len(out) == 0:
        raise ValidationError("Demand frame has no rows.", details={"domain": domain.value})
    if bool((out[cols.quantity] == 0).all()):
        notes.append("All demand quantities are zero. This is valid but uninformative for forecasting.")
    return ValidatedFrame(domain=domain, frame=out.reset_index(drop=True), row_count=len(out), notes=tuple(notes))


def validate_inventory_batches(
    frame: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> ValidatedFrame:
    """Validate batch on-hand records.

    Expired stock is still a valid *record*. Eligibility/optimization must treat
    expiry separately and must not allocate expired quantity.
    """
    cfg = _cfg(config)
    cols = cfg.columns
    domain = DataDomain.INVENTORY_BATCHES
    _require_dataframe(frame, domain=domain)
    required = [cols.batch_id, cols.sku_id, cols.warehouse_id, cols.quantity]
    _require_columns(frame, required, domain=domain)
    optional_dates = [name for name in (cols.expiry_date, cols.received_date) if name in frame.columns]
    keep = required + optional_dates
    if cols.remaining_shelf_life_days in frame.columns:
        keep.append(cols.remaining_shelf_life_days)
    out = frame.loc[:, keep].copy()
    _reject_nulls(out, required, domain=domain)
    out = _stringify_ids(out, [cols.batch_id, cols.sku_id, cols.warehouse_id])
    out[cols.quantity] = _require_numeric_non_negative(
        out[cols.quantity], column=cols.quantity, domain=domain, allow_zero=True
    )
    for date_col in optional_dates:
        _reject_nulls(out, [date_col], domain=domain)
        out[date_col] = _parse_date_series(out[date_col], column=date_col, domain=domain)
    if cols.remaining_shelf_life_days in out.columns:
        _reject_nulls(out, [cols.remaining_shelf_life_days], domain=domain)
        out[cols.remaining_shelf_life_days] = _require_numeric_non_negative(
            out[cols.remaining_shelf_life_days],
            column=cols.remaining_shelf_life_days,
            domain=domain,
            allow_zero=True,
            integer_like=True,
        )
    _assert_unique(out, [cols.batch_id], domain=domain)
    if len(out) == 0:
        raise ValidationError("Inventory batch frame has no rows.", details={"domain": domain.value})
    notes = (
        "Expiry does not fail schema validation. Allocation must still refuse expired or unusable batches.",
    )
    return ValidatedFrame(domain=domain, frame=out.reset_index(drop=True), row_count=len(out), notes=notes)


def validate_lanes(
    frame: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> ValidatedFrame:
    cfg = _cfg(config)
    cols = cfg.columns
    domain = DataDomain.LANES
    _require_dataframe(frame, domain=domain)
    required = [cols.warehouse_id, cols.destination_id, cols.is_available]
    _require_columns(frame, required, domain=domain)
    keep = list(required)
    if cols.transit_days in frame.columns:
        keep.append(cols.transit_days)
    out = frame.loc[:, keep].copy()
    _reject_nulls(out, required, domain=domain)
    out = _stringify_ids(out, [cols.warehouse_id, cols.destination_id])
    if not pd.api.types.is_bool_dtype(out[cols.is_available]):
        truthy = {True, False, 1, 0, "true", "false", "True", "False", "1", "0"}
        raw = out[cols.is_available]
        if bool(raw.isna().any()) or not all(v in truthy for v in raw.tolist()):
            raise ValidationError(
                f"Column {cols.is_available!r} must be boolean (or 0/1 / true/false). Unknown values are not coerced.",
                details={"domain": domain.value, "unique_sample": list(map(repr, raw.unique()[:10]))},
            )
        mapped = raw.map(
            {
                True: True,
                False: False,
                1: True,
                0: False,
                "1": True,
                "0": False,
                "true": True,
                "false": False,
                "True": True,
                "False": False,
            }
        )
        out[cols.is_available] = mapped.astype(bool)
    if cols.transit_days in out.columns:
        _reject_nulls(out, [cols.transit_days], domain=domain)
        out[cols.transit_days] = _require_numeric_non_negative(
            out[cols.transit_days],
            column=cols.transit_days,
            domain=domain,
            allow_zero=True,
            integer_like=True,
        )
    _assert_unique(out, [cols.warehouse_id, cols.destination_id], domain=domain)
    if len(out) == 0:
        raise ValidationError("Lane frame has no rows.", details={"domain": domain.value})
    unavailable = int((~out[cols.is_available]).sum())
    notes = ()
    if unavailable:
        notes = (f"{unavailable} lane(s) are marked unavailable and must not be used for allocation.",)
    return ValidatedFrame(domain=domain, frame=out.reset_index(drop=True), row_count=len(out), notes=notes)


def validate_transport_costs(
    frame: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> ValidatedFrame:
    cfg = _cfg(config)
    cols = cfg.columns
    domain = DataDomain.TRANSPORT_COSTS
    _require_dataframe(frame, domain=domain)
    required = [cols.warehouse_id, cols.destination_id, cols.unit_transport_cost]
    _require_columns(frame, required, domain=domain)
    keep = list(required)
    sku_level = cols.sku_id in frame.columns
    if sku_level:
        keep.append(cols.sku_id)
    out = frame.loc[:, keep].copy()
    _reject_nulls(out, required, domain=domain)
    id_cols = [cols.warehouse_id, cols.destination_id]
    if sku_level:
        _reject_nulls(out, [cols.sku_id], domain=domain)
        id_cols.append(cols.sku_id)
    out = _stringify_ids(out, id_cols)
    out[cols.unit_transport_cost] = _require_numeric_non_negative(
        out[cols.unit_transport_cost],
        column=cols.unit_transport_cost,
        domain=domain,
        allow_zero=True,
    )
    _assert_unique(out, id_cols, domain=domain)
    if len(out) == 0:
        raise ValidationError("Transport cost frame has no rows.", details={"domain": domain.value})
    notes = (
        "Costs are treated as currency per quantity unit. Confirm the currency and unit with Rahul.",
    )
    if not sku_level:
        notes = notes + ("sku_id is absent; costs are interpreted as lane-level (all SKUs share the lane cost).",)
    return ValidatedFrame(domain=domain, frame=out.reset_index(drop=True), row_count=len(out), notes=notes)


def validate_capacities(
    frame: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> ValidatedFrame:
    cfg = _cfg(config)
    cols = cfg.columns
    domain = DataDomain.CAPACITIES
    _require_dataframe(frame, domain=domain)
    required = [cols.destination_id, cols.capacity_units]
    _require_columns(frame, required, domain=domain)
    keep = list(required)
    if cols.sku_id in frame.columns:
        keep.append(cols.sku_id)
    if cols.warehouse_id in frame.columns:
        keep.append(cols.warehouse_id)
    if cols.effective_date in frame.columns:
        keep.append(cols.effective_date)
    out = frame.loc[:, keep].copy()
    _reject_nulls(out, required, domain=domain)
    id_cols = [cols.destination_id]
    if cols.sku_id in out.columns:
        _reject_nulls(out, [cols.sku_id], domain=domain)
        id_cols.append(cols.sku_id)
    if cols.warehouse_id in out.columns:
        _reject_nulls(out, [cols.warehouse_id], domain=domain)
        id_cols.append(cols.warehouse_id)
    out = _stringify_ids(out, id_cols)
    out[cols.capacity_units] = _require_numeric_non_negative(
        out[cols.capacity_units], column=cols.capacity_units, domain=domain, allow_zero=True
    )
    if cols.effective_date in out.columns:
        _reject_nulls(out, [cols.effective_date], domain=domain)
        out[cols.effective_date] = _parse_date_series(
            out[cols.effective_date], column=cols.effective_date, domain=domain
        )
        id_cols.append(cols.effective_date)
    _assert_unique(out, id_cols, domain=domain)
    if len(out) == 0:
        raise ValidationError("Capacity frame has no rows.", details={"domain": domain.value})
    return ValidatedFrame(
        domain=domain,
        frame=out.reset_index(drop=True),
        row_count=len(out),
        notes=("Capacity grain (per destination / SKU / day) is proposed, not confirmed.",),
    )


def validate_forecast_frame(
    frame: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> ValidatedFrame:
    """Schema check for forecast outputs. Used by later tasks and contract tests."""
    cfg = _cfg(config)
    cols = cfg.columns
    domain = DataDomain.FORECAST
    _require_dataframe(frame, domain=domain)
    required = [
        cols.sku_id,
        cols.destination_id,
        cols.forecast_origin,
        cols.forecast_date,
        cols.horizon_day,
        cols.point_forecast,
        cols.forecast_status,
        cols.model_name,
    ]
    _require_columns(frame, required, domain=domain)
    optional = [
        name
        for name in (
            cols.lower_bound,
            cols.upper_bound,
            cols.interval_width,
            cols.uncertainty_status,
        )
        if name in frame.columns
    ]
    out = frame.loc[:, required + optional].copy()
    if out.empty:
        raise ValidationError("Forecast frame has no rows.", details={"domain": domain.value})
    _reject_nulls(
        out,
        [cols.sku_id, cols.destination_id, cols.forecast_origin, cols.forecast_date, cols.horizon_day, cols.forecast_status, cols.model_name],
        domain=domain,
    )
    out = _stringify_ids(out, [cols.sku_id, cols.destination_id, cols.forecast_status, cols.model_name])
    out[cols.forecast_origin] = _parse_date_series(out[cols.forecast_origin], column=cols.forecast_origin, domain=domain)
    out[cols.forecast_date] = _parse_date_series(out[cols.forecast_date], column=cols.forecast_date, domain=domain)
    horizon = pd.to_numeric(out[cols.horizon_day], errors="coerce")
    if bool(horizon.isna().any()) or bool(((horizon % 1) != 0).any()):
        raise ValidationError("horizon_day must be a whole number.", details={"domain": domain.value})
    horizon = horizon.astype("int64")
    max_h = cfg.forecast.horizon_days
    if bool((horizon < 1).any()) or bool((horizon > max_h).any()):
        raise ValidationError(
            "horizon_day is outside the configured forecast horizon.",
            details={"domain": domain.value, "allowed": [1, max_h]},
        )
    out[cols.horizon_day] = horizon
    expected_dates = out[cols.forecast_origin] + pd.to_timedelta(out[cols.horizon_day], unit="D")
    if bool((out[cols.forecast_date] != expected_dates).any()):
        raise ValidationError("forecast_date must equal forecast_origin plus horizon_day.")
    ok_mask = out[cols.forecast_status].eq(ForecastStatus.OK.value)
    numeric = pd.to_numeric(out.loc[ok_mask, cols.point_forecast], errors="coerce")
    if bool(ok_mask.any()):
        finite = numeric.map(lambda value: pd.notna(value) and abs(float(value)) != float("inf"))
        if bool(numeric.isna().any()) or not bool(finite.all()) or bool((numeric < 0).any()):
            raise ValidationError(
                "Successful forecasts must have a non-negative numeric point_forecast. Failures may use NA.",
                details={"domain": domain.value},
            )
        out.loc[ok_mask, cols.point_forecast] = numeric.astype("float64")
    point_values = out[cols.point_forecast]
    supplied_points = point_values.notna()
    parsed_points = pd.to_numeric(point_values.loc[supplied_points], errors="coerce")
    finite_points = parsed_points.map(
        lambda value: pd.notna(value) and abs(float(value)) != float("inf")
    )
    if (
        parsed_points.isna().any()
        or not bool(finite_points.all())
        or bool((parsed_points < 0).any())
    ):
        raise ValidationError("Provided forecasts must be finite and non-negative.")
    interval_columns = (cols.lower_bound, cols.upper_bound, cols.interval_width)
    supplied_intervals = [column for column in interval_columns if column in out.columns]
    if supplied_intervals and len(supplied_intervals) != len(interval_columns):
        raise SchemaError(
            "Forecast intervals must provide lower_bound, upper_bound, and interval_width together.",
            details={"present_columns": supplied_intervals},
        )
    if supplied_intervals:
        for column in supplied_intervals:
            out[column] = pd.to_numeric(out[column], errors="coerce")
        estimated = (
            out[cols.uncertainty_status].eq("estimated")
            if cols.uncertainty_status in out.columns
            else out[cols.lower_bound].notna()
        )
        interval_values = out.loc[estimated, list(interval_columns)]
        finite = interval_values.apply(
            lambda column: column.map(
                lambda value: pd.notna(value) and abs(float(value)) != float("inf")
            )
        )
        if (
            interval_values.isna().any().any()
            or not finite.all().all()
            or (interval_values < 0).any().any()
        ):
            raise ValidationError("Estimated forecast intervals must be finite and non-negative.")
        if bool(estimated.any()):
            lower = out.loc[estimated, cols.lower_bound]
            point = pd.to_numeric(out.loc[estimated, cols.point_forecast], errors="coerce")
            upper = out.loc[estimated, cols.upper_bound]
            if bool((lower > point).any()) or bool((point > upper).any()):
                raise ValidationError("Forecast point must lie within its uncertainty interval.")
        if cols.uncertainty_status not in out.columns:
            out[cols.uncertainty_status] = out[cols.lower_bound].notna().map(
                {True: "estimated", False: "insufficient_residuals"}
            )
    _assert_unique(
        out,
        [cols.sku_id, cols.destination_id, cols.forecast_origin, cols.forecast_date, cols.model_name],
        domain=domain,
    )
    return ValidatedFrame(domain=domain, frame=out.reset_index(drop=True), row_count=len(out), notes=())


def proposed_column_catalog(columns: ColumnMap | None = None) -> Mapping[str, list[str]]:
    """Document the proposed columns per domain for ASSUMPTIONS.md / contracts."""
    cols = columns or ColumnMap()
    return {
        DataDomain.RAW_DEMAND.value: [cols.sku_id, cols.destination_id, cols.demand_date, cols.quantity],
        DataDomain.INVENTORY_BATCHES.value: [
            cols.batch_id,
            cols.sku_id,
            cols.warehouse_id,
            cols.quantity,
            cols.expiry_date,
            cols.received_date,
            cols.remaining_shelf_life_days,
        ],
        DataDomain.LANES.value: [cols.warehouse_id, cols.destination_id, cols.is_available, cols.transit_days],
        DataDomain.TRANSPORT_COSTS.value: [
            cols.warehouse_id,
            cols.destination_id,
            cols.sku_id,
            cols.unit_transport_cost,
        ],
        DataDomain.CAPACITIES.value: [cols.destination_id, cols.sku_id, cols.capacity_units, cols.effective_date],
        DataDomain.FORECAST.value: [
            cols.sku_id,
            cols.destination_id,
            cols.forecast_origin,
            cols.forecast_date,
            cols.horizon_day,
            cols.point_forecast,
            cols.forecast_status,
            cols.model_name,
        ],
    }
