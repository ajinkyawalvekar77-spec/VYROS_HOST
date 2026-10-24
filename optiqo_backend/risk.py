"""Measured, network-level supply-risk indicators for demo and request data."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from .demo_data import generate_demo_data
from .engine_adapter import (
    _load_engine,
    frame_from_rows,
    json_safe,
    run_forecast,
)
from .schemas import DatasetPayload


def _eligible_stock_by_sku(
    *,
    inventory_rows: list[dict[str, Any]],
    lane_rows: list[dict[str, Any]],
    shelf_life: dict[str, int],
    forecast: Any,
) -> pd.Series:
    engine = _load_engine()
    inventory = frame_from_rows(inventory_rows)
    lanes = frame_from_rows(lane_rows)
    engine["validate_inventory_batches"](inventory, config=forecast.config)
    engine["validate_lanes"](lanes, config=forecast.config)
    candidates = engine["eligible_shipments"](
        inventory,
        lanes,
        shelf_life,
        origin_date=forecast.response["origin"],
        config=forecast.config,
    )
    if candidates.empty:
        return pd.Series(dtype=float)
    return (
        candidates.drop_duplicates("batch_id")
        .groupby("sku_id")["quantity"]
        .sum()
    )


def _risk_indicators(
    forecast: Any,
    *,
    sku_stock: pd.Series | None,
) -> list[dict[str, Any]]:
    indicators: list[dict[str, Any]] = []
    for sku_id, rows in forecast.frame.groupby("sku_id", sort=True):
        demand = float(rows["point_forecast"].sum())
        lower = (
            float(rows["lower_bound"].sum())
            if "lower_bound" in rows and rows["lower_bound"].notna().all()
            else None
        )
        upper = (
            float(rows["upper_bound"].sum())
            if "upper_bound" in rows and rows["upper_bound"].notna().all()
            else None
        )
        indicators.append(
            {
                "name": "forecast_uncertainty_interval",
                "kind": "measured_forecast_interval",
                "sku_id": str(sku_id),
                "point_demand_units": demand,
                "lower_demand_units": lower,
                "upper_demand_units": upper,
                "interval_width_units": (
                    upper - lower
                    if lower is not None and upper is not None
                    else None
                ),
            }
        )
        if sku_stock is not None:
            stock = float(sku_stock.get(sku_id, 0.0))
            shortage = max(0.0, demand - stock)
            average_daily = demand / forecast.response["horizon_days"]
            indicators.append(
                {
                    "name": "network_supply_shortage",
                    "kind": "measured_eligible_network_stock_vs_forecast",
                    "sku_id": str(sku_id),
                    "is_flagged": shortage > 0,
                    "usable_network_stock_units": stock,
                    "forecast_horizon_demand_units": demand,
                    "supply_shortage_units": shortage,
                    "network_days_of_cover": (
                        stock / average_daily if average_daily > 0 else None
                    ),
                }
            )
    return indicators


def _risk_response(
    *,
    indicators: list[dict[str, Any]],
    synthetic: bool,
    seed: int | None,
    scope: str,
    dataset_id: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    unavailable = [
        "destination-level expected unmet share (no destination on-hand input)",
        "expected expiry loss (no scenario expiry-cost inputs)",
        "financial exposure (no approved margin or landed-cost inputs)",
    ]
    if "eligible network stock" not in scope:
        unavailable.append(
            "eligible network stock versus forecast demand (inventory_batches and lanes are both required)"
        )
    limitations = [
        "A batch is counted once if it is eligible for at least one destination; the indicator does not allocate that stock to a destination.",
        "Supply shortage is a measured deterministic comparison, not a probability or weighted risk score.",
    ]
    if dataset_id is not None:
        limitations.extend(
            [
                "Indicators are calculated from the dataset included in this request and are not persisted as an operational record.",
                "Synthetic-data status is inherited from the submitted dataset and is not independently verified.",
            ]
        )
    else:
        limitations.append(
            "Synthetic demo data are used because this request does not identify a user dataset or run."
        )
    return json_safe(
        {
            "dataset_id": dataset_id,
            "synthetic": synthetic,
            "seed": seed,
            "indicator_scope": scope,
            "risk_score": None,
            "severity": None,
            "model_name": model_name,
            "indicators": indicators,
            "unavailable_indicators": unavailable,
            "limitations": limitations,
        }
    )


def demo_supply_risks(*, seed: int = 42) -> dict[str, Any]:
    """Measure horizon demand against uniquely counted eligible network stock."""
    dataset = generate_demo_data(seed=seed, profile="compact")
    forecast = run_forecast(dataset["demand_history"])
    sku_stock = _eligible_stock_by_sku(
        inventory_rows=dataset["inventory_batches"],
        lane_rows=dataset["lanes"],
        shelf_life=dataset["sku_min_shelf_life_days"],
        forecast=forecast,
    )
    indicators = _risk_indicators(forecast, sku_stock=sku_stock)
    indicators.sort(
        key=lambda item: (
            item.get("name") != "network_supply_shortage",
            -float(item.get("supply_shortage_units", 0.0)),
            str(item.get("sku_id", "")),
        )
    )
    return _risk_response(
        indicators=indicators,
        synthetic=True,
        seed=seed,
        scope="SKU-level eligible network stock versus forecast demand",
        model_name=forecast.response["model_name"],
    )


def dataset_supply_risks(payload: DatasetPayload) -> dict[str, Any]:
    """Calculate supported forecast and eligible-stock indicators for one request dataset."""
    dataset = payload.model_dump(mode="json")
    canonical = json.dumps(
        dataset, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    dataset_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    forecast = run_forecast(payload.demand_history, origin=payload.as_of)
    has_stock_inputs = bool(payload.inventory_batches and payload.lanes)
    sku_stock = (
        _eligible_stock_by_sku(
            inventory_rows=payload.inventory_batches,
            lane_rows=payload.lanes,
            shelf_life=payload.sku_min_shelf_life_days,
            forecast=forecast,
        )
        if has_stock_inputs
        else None
    )
    indicators = _risk_indicators(forecast, sku_stock=sku_stock)
    scope = (
        "SKU-level forecast uncertainty and eligible network stock versus forecast demand"
        if has_stock_inputs
        else "SKU-level forecast uncertainty; inventory risk unavailable"
    )
    return _risk_response(
        indicators=indicators,
        synthetic=payload.synthetic,
        seed=payload.seed,
        scope=scope,
        dataset_id=dataset_id,
        model_name=forecast.response["model_name"],
    )
