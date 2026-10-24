"""Engine configuration for Task 1.

Column names are a *proposed* contract, not a confirmed backend schema.
Change ``ColumnMap`` fields to adapt without rewriting validation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ColumnMap:
    """Proposed column names. Confirm with Rahul before treating as stable."""

    sku_id: str = "sku_id"
    destination_id: str = "destination_id"
    warehouse_id: str = "warehouse_id"
    batch_id: str = "batch_id"
    demand_date: str = "demand_date"
    quantity: str = "quantity"
    expiry_date: str = "expiry_date"
    received_date: str = "received_date"
    remaining_shelf_life_days: str = "remaining_shelf_life_days"
    is_available: str = "is_available"
    transit_days: str = "transit_days"
    unit_transport_cost: str = "unit_transport_cost"
    capacity_units: str = "capacity_units"
    effective_date: str = "effective_date"
    forecast_date: str = "forecast_date"
    forecast_origin: str = "forecast_origin"
    horizon_day: str = "horizon_day"
    point_forecast: str = "point_forecast"
    forecast_status: str = "forecast_status"
    model_name: str = "model_name"
    lower_bound: str = "lower_bound"
    upper_bound: str = "upper_bound"
    interval_width: str = "interval_width"
    uncertainty_status: str = "uncertainty_status"


@dataclass(frozen=True)
class ForecastConfig:
    horizon_days: int = 7
    seasonal_lag_days: int = 7
    moving_average_window_days: int = 28
    moving_average_min_periods: int = 28
    lag_days: tuple[int, ...] = (1, 7, 14, 28)
    rolling_windows_days: tuple[int, ...] = (7, 14, 28)
    min_history_days_for_seasonal_naive: int = 7
    uncertainty_confidence_level: float = 0.90
    min_uncertainty_residuals: int = 5


@dataclass(frozen=True)
class SplitConfig:
    """Chronological partitions. Explicit dates take precedence over fractions."""

    train_end: date | None = None
    validation_end: date | None = None
    test_end: date | None = None
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    min_unique_dates: int = 3


@dataclass(frozen=True)
class EngineConfig:
    columns: ColumnMap = field(default_factory=ColumnMap)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    group_keys: tuple[str, str] = ("sku_id", "destination_id")

    def demand_group_columns(self) -> tuple[str, str]:
        return (self.columns.sku_id, self.columns.destination_id)
