
"""Batch, lane, and destination eligibility for inventory allocation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import pandas as pd

from ..config import EngineConfig
from ..exceptions import SchemaError, ValidationError
from ..schemas import validate_inventory_batches, validate_lanes


def eligible_shipments(
    inventory_batches: pd.DataFrame,
    lanes: pd.DataFrame,
    sku_min_shelf_life_days: Mapping[str, int],
    *,
    origin_date: str | date | pd.Timestamp,
    config: EngineConfig | None = None,
) -> pd.DataFrame:
    """Return eligible batch-to-destination shipment combinations.

    A combination is eligible only when:
    - the batch has positive stock;
    - its warehouse-to-destination lane is available;
    - transit time is known;
    - remaining shelf life at arrival meets the SKU requirement.

    `sku_min_shelf_life_days` maps each SKU ID to its required minimum
    remaining shelf life in whole days.

    The function does not allocate stock. It returns eligible options
    for the downstream optimizer.
    """
    cfg = config or EngineConfig()
    cols = cfg.columns

    if not isinstance(sku_min_shelf_life_days, Mapping):
        raise TypeError("sku_min_shelf_life_days must be a mapping of SKU IDs to days.")

    try:
        origin = pd.Timestamp(origin_date).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError("origin_date must be a valid date.") from exc

    if pd.isna(origin):
        raise ValueError("origin_date must be a valid date.")

    minimum_life: dict[str, int] = {}
    for sku, days in sku_min_shelf_life_days.items():
        sku_key = str(sku).strip()
        if not sku_key or sku_key.lower() == "nan":
            raise ValueError("SKU IDs in the shelf-life mapping cannot be empty.")
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise ValueError(
                f"Minimum shelf life for SKU {sku_key!r} must be a non-negative integer."
            )
        minimum_life[sku_key] = days

    batches = validate_inventory_batches(
        inventory_batches, config=cfg
    ).frame
    lane_frame = validate_lanes(lanes, config=cfg).frame

    if cols.transit_days not in lane_frame.columns:
        raise SchemaError(
            f"Lane data must include {cols.transit_days!r} to calculate arrival shelf life."
        )

    has_expiry = cols.expiry_date in batches.columns
    has_remaining_life = cols.remaining_shelf_life_days in batches.columns

    if not has_expiry and not has_remaining_life:
        raise SchemaError(
            "Inventory batches must include expiry_date or "
            "remaining_shelf_life_days to verify shelf-life eligibility."
        )

    batch_skus = set(batches[cols.sku_id])
    missing_requirements = sorted(batch_skus - set(minimum_life))
    if missing_requirements:
        raise ValidationError(
            "Minimum shelf-life requirements are missing for one or more SKUs.",
            details={"missing_sku_ids": missing_requirements},
        )

    available_lanes = lane_frame.loc[
        lane_frame[cols.is_available].astype(bool)
    ].copy()

    # Only connect batches to lanes originating at the batch's warehouse.
    candidates = batches.merge(
        available_lanes,
        on=cols.warehouse_id,
        how="inner",
        suffixes=("_batch", "_lane"),
    )

    # Keep only positive-stock batches.
    candidates = candidates.loc[candidates[cols.quantity] > 0].copy()

    if candidates.empty:
        return pd.DataFrame(
            columns=[
                cols.batch_id,
                cols.sku_id,
                cols.warehouse_id,
                cols.destination_id,
                cols.quantity,
                "arrival_date",
                "remaining_shelf_life_days_at_arrival",
                "minimum_shelf_life_days",
            ]
        )

    candidates["arrival_date"] = (
        origin + pd.to_timedelta(candidates[cols.transit_days], unit="D")
    )

    if has_expiry:
        candidates["remaining_shelf_life_days_at_arrival"] = (
            candidates[cols.expiry_date] - candidates["arrival_date"]
        ).dt.days
    else:
        candidates["remaining_shelf_life_days_at_arrival"] = (
            candidates[cols.remaining_shelf_life_days]
            - candidates[cols.transit_days]
        )

    candidates["minimum_shelf_life_days"] = candidates[cols.sku_id].map(
        minimum_life
    )

    eligible_mask = (
        candidates["remaining_shelf_life_days_at_arrival"]
        >= candidates["minimum_shelf_life_days"]
    )

    output_columns = [
        cols.batch_id,
        cols.sku_id,
        cols.warehouse_id,
        cols.destination_id,
        cols.quantity,
        "arrival_date",
        "remaining_shelf_life_days_at_arrival",
        "minimum_shelf_life_days",
    ]
    if has_expiry:
        output_columns.append(cols.expiry_date)

    result = candidates.loc[eligible_mask, output_columns].copy()
    result["arrival_date"] = pd.to_datetime(result["arrival_date"]).dt.normalize()

    return result.reset_index(drop=True)
