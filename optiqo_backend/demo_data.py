"""Seeded, internally consistent synthetic data for API demos."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd


PROFILES: dict[str, tuple[int, int, int, int]] = {
    "compact": (3, 3, 2, 84),
    "prd": (30, 40, 4, 420),
}


def generate_demo_data(
    *, seed: int = 42, profile: Literal["compact", "prd"] = "compact"
) -> dict[str, Any]:
    """Generate synthetic demand, stock, routes, costs, and held-out actuals.

    Compact data is intended for interactive API demos and integration tests.
    The `prd` profile uses 30 SKUs, 40 destinations, 4 warehouses, and 420
    historical days, matching the PRD's documented default data scale.
    """
    if profile not in PROFILES:
        raise ValueError(f"Unsupported demo profile {profile!r}.")
    sku_count, destination_count, warehouse_count, history_days = PROFILES[profile]
    rng = np.random.default_rng(seed)
    start = date(2024, 1, 1)
    origin = start + timedelta(days=history_days - 1)
    skus = [f"SKU-{index + 1:03d}" for index in range(sku_count)]
    destinations = [f"DEST-{index + 1:03d}" for index in range(destination_count)]
    warehouses = [f"WH-{index + 1:02d}" for index in range(warehouse_count)]

    sku_daily_rates = rng.uniform(7.0, 14.0, size=sku_count)
    destination_factors = rng.uniform(0.75, 1.3, size=destination_count)
    weekday_factors = np.array([0.93, 1.0, 1.02, 1.05, 1.1, 1.16, 0.82])
    demand_rows: list[dict[str, Any]] = []
    total_demand_by_sku = {sku: 0.0 for sku in skus}
    for day_index in range(history_days):
        demand_date = start + timedelta(days=day_index)
        weekday_factor = weekday_factors[demand_date.weekday()]
        for sku_index, sku in enumerate(skus):
            for destination_index, destination in enumerate(destinations):
                mean = (
                    sku_daily_rates[sku_index]
                    * destination_factors[destination_index]
                    * weekday_factor
                )
                quantity = float(rng.poisson(mean))
                demand_rows.append(
                    {
                        "sku_id": sku,
                        "destination_id": destination,
                        "demand_date": demand_date,
                        "quantity": quantity,
                    }
                )
                total_demand_by_sku[sku] += quantity

    evaluation_rows: list[dict[str, Any]] = []
    for day_index in range(1, 57):
        demand_date = origin + timedelta(days=day_index)
        weekday_factor = weekday_factors[demand_date.weekday()]
        for sku_index, sku in enumerate(skus):
            for destination_index, destination in enumerate(destinations):
                mean = (
                    sku_daily_rates[sku_index]
                    * destination_factors[destination_index]
                    * weekday_factor
                )
                evaluation_rows.append(
                    {
                        "sku_id": sku,
                        "destination_id": destination,
                        "demand_date": demand_date,
                        "quantity": float(rng.poisson(mean)),
                    }
                )

    lanes: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []
    for warehouse_index, warehouse in enumerate(warehouses):
        for destination_index, destination in enumerate(destinations):
            available = (warehouse_index + destination_index) % 3 != 0
            lanes.append(
                {
                    "warehouse_id": warehouse,
                    "destination_id": destination,
                    "is_available": available,
                    "transit_days": 1 + (warehouse_index + destination_index) % 3,
                }
            )
            costs.append(
                {
                    "warehouse_id": warehouse,
                    "destination_id": destination,
                    "unit_transport_cost": float(
                        2.0 + 0.7 * warehouse_index + 0.25 * destination_index
                    ),
                }
            )

    stock_rows: list[dict[str, Any]] = []
    for sku in skus:
        total_weekly_stock = max(1, int(total_demand_by_sku[sku] / history_days * 7 * 1.05))
        for warehouse_index, warehouse in enumerate(warehouses):
            for batch_index in range(2):
                portion = total_weekly_stock / (warehouse_count * 2)
                quantity = max(1, int(round(portion + rng.uniform(-0.08, 0.08) * portion)))
                stock_rows.append(
                    {
                        "batch_id": f"B-{sku}-{warehouse}-{batch_index + 1}",
                        "sku_id": sku,
                        "warehouse_id": warehouse,
                        "quantity": float(quantity),
                        "expiry_date": origin + timedelta(days=120 + 20 * batch_index),
                    }
                )

    receipt_rows: list[dict[str, Any]] = []
    for week in range(1, 8):
        arrival_date = origin + timedelta(days=week * 7)
        for sku in skus:
            weekly_mean = total_demand_by_sku[sku] / history_days * 7
            receipt_total = int(round(weekly_mean * 0.99))
            for warehouse_index, warehouse in enumerate(warehouses):
                base, remainder = divmod(receipt_total, warehouse_count)
                quantity = base + (1 if warehouse_index < remainder else 0)
                if quantity == 0:
                    continue
                receipt_rows.append(
                    {
                        "receipt_id": f"R-{week:02d}-{sku}-{warehouse}",
                        "batch_id": f"RB-{week:02d}-{sku}-{warehouse}",
                        "sku_id": sku,
                        "warehouse_id": warehouse,
                        "quantity": float(quantity),
                        "arrival_date": arrival_date,
                        "expiry_date": origin + timedelta(days=240),
                    }
                )

    capacity_per_destination = max(
        1.0,
        sum(sku_daily_rates) * max(destination_factors) * 7 * 1.5,
    )
    return {
        "synthetic": True,
        "seed": seed,
        "profile": profile,
        "as_of": origin,
        "generation_rules": [
            "A NumPy default_rng initialized with the response seed drives every random draw.",
            "SKU daily rates are uniform on [7, 14]; destination factors are uniform on [0.75, 1.30]. Daily demand is a Poisson draw of SKU rate times destination factor times weekday factor [0.93, 1.00, 1.02, 1.05, 1.10, 1.16, 0.82] for Monday through Sunday.",
            "Each SKU has two batches per warehouse. Total stock targets 105% of its historical average weekly network demand, split across warehouses and batches with seeded +/-8% variation; expiry is origin +120 or +140 days.",
            "Lane (warehouse index w, destination index d) is available when (w+d) modulo 3 is nonzero; transit days are 1+(w+d) modulo 3, and unit transport cost is 2.00+0.70w+0.25d synthetic cost units.",
            "Capacity is shared by SKU at each destination and equals 1.5 times the sum of SKU rates times the largest destination factor times seven days. Each SKU has a seven-day minimum shelf-life rule.",
            "Held-out actuals cover 56 dates after the history origin and use the same seeded Poisson demand process; held_out_actuals preserves the first seven days for the plan endpoint.",
            "Seven exogenous weekly warehouse receipt waves arrive on days 7 through 49; each supplies 99% of recent average weekly network demand per SKU, split evenly among warehouses. Receipts are identical across policies and expire 240 days after origin.",
        ],
        "demand_history": demand_rows,
        "inventory_batches": stock_rows,
        "lanes": lanes,
        "transport_costs": costs,
        "capacities": [
            {
                "destination_id": destination,
                "capacity_units": float(capacity_per_destination),
            }
            for destination in destinations
        ],
        "sku_min_shelf_life_days": {sku: 7 for sku in skus},
        "held_out_actuals": evaluation_rows[: 7 * sku_count * destination_count],
        "evaluation_actuals": evaluation_rows,
        "warehouse_receipts": receipt_rows,
    }
