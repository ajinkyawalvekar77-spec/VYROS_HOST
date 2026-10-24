"""Deterministic forecast baselines.

These methods do not use LightGBM. They never look past the forecast origin.
Insufficient history is returned as a row-level status; it is not filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import EngineConfig
from ..exceptions import ValidationError
from ..schemas import ForecastStatus, validate_demand, validate_forecast_frame


def _horizon_dates(origin: pd.Timestamp, horizon_days: int) -> list[tuple[int, pd.Timestamp]]:
    return [(h, origin + pd.Timedelta(days=h)) for h in range(1, horizon_days + 1)]


@dataclass
class SeasonalNaiveBaseline:
    """Predict demand at date d as observed demand at d minus ``seasonal_lag_days``.

    Requires the lagged date to exist for that series. Calendar gaps are not
    interpolated.
    """

    config: EngineConfig = field(default_factory=EngineConfig)
    _history: pd.DataFrame | None = None
    name: str = "seasonal_naive"

    def fit(self, history: pd.DataFrame, *, already_validated: bool = False) -> "SeasonalNaiveBaseline":
        cfg = self.config
        frame = history if already_validated else validate_demand(history, config=cfg).frame
        self._history = frame.copy()
        return self

    def predict(self, *, origin: pd.Timestamp | str, keys: pd.DataFrame | None = None) -> pd.DataFrame:
        if self._history is None:
            raise ValidationError("Seasonal naive baseline must be fit before predict.")
        cfg = self.config
        cols = cfg.columns
        origin_ts = pd.Timestamp(origin).normalize()
        usable = self._history.loc[self._history[cols.demand_date] <= origin_ts].copy()
        usable[cols.demand_date] = pd.to_datetime(usable[cols.demand_date]).dt.normalize()
        if keys is None:
            key_frame = usable[list(cfg.demand_group_columns())].drop_duplicates()
        else:
            key_frame = keys[list(cfg.demand_group_columns())].drop_duplicates()
        lag = cfg.forecast.seasonal_lag_days
        lookup = usable.set_index(list(cfg.demand_group_columns()) + [cols.demand_date])[cols.quantity]
        rows: list[dict[str, object]] = []
        for rec in key_frame.to_dict(orient="records"):
            sku = rec[cols.sku_id]
            dest = rec[cols.destination_id]
            for horizon, forecast_date in _horizon_dates(origin_ts, cfg.forecast.horizon_days):
                lagged_date = forecast_date - pd.Timedelta(days=lag)
                key = (sku, dest, lagged_date)
                if key in lookup.index and lagged_date <= origin_ts:
                    value = float(lookup.loc[key])
                    status = ForecastStatus.OK.value
                    point: float | None = value
                else:
                    status = ForecastStatus.INSUFFICIENT_HISTORY.value
                    point = None
                rows.append(
                    {
                        cols.sku_id: sku,
                        cols.destination_id: dest,
                        cols.forecast_origin: origin_ts,
                        cols.forecast_date: forecast_date,
                        cols.horizon_day: horizon,
                        cols.point_forecast: point,
                        cols.forecast_status: status,
                        cols.model_name: self.name,
                    }
                )
        result = pd.DataFrame(rows)
        return validate_forecast_frame(result, config=cfg).frame


@dataclass
class MovingAverageBaseline:
    """Mean demand over the last ``moving_average_window_days`` calendar days at or before origin.

    The same origin-level mean is used for every horizon day. If fewer than
    ``moving_average_min_periods`` observations exist in that window, the series
    is marked insufficient rather than using a shorter window.
    """

    config: EngineConfig = field(default_factory=EngineConfig)
    _history: pd.DataFrame | None = None
    name: str = "moving_average_28"

    def fit(self, history: pd.DataFrame, *, already_validated: bool = False) -> "MovingAverageBaseline":
        cfg = self.config
        frame = history if already_validated else validate_demand(history, config=cfg).frame
        self._history = frame.copy()
        return self

    def predict(self, *, origin: pd.Timestamp | str, keys: pd.DataFrame | None = None) -> pd.DataFrame:
        if self._history is None:
            raise ValidationError("Moving-average baseline must be fit before predict.")
        cfg = self.config
        cols = cfg.columns
        origin_ts = pd.Timestamp(origin).normalize()
        window = cfg.forecast.moving_average_window_days
        min_periods = cfg.forecast.moving_average_min_periods
        window_start = origin_ts - pd.Timedelta(days=window - 1)
        usable = self._history.loc[
            (self._history[cols.demand_date] >= window_start) & (self._history[cols.demand_date] <= origin_ts)
        ]
        history_keys = self._history.loc[self._history[cols.demand_date] <= origin_ts]
        if keys is None:
            key_frame = history_keys[list(cfg.demand_group_columns())].drop_duplicates()
        else:
            key_frame = keys[list(cfg.demand_group_columns())].drop_duplicates()

        grouped = usable.groupby(list(cfg.demand_group_columns()), sort=False)[cols.quantity]
        stats = grouped.agg(["mean", "count"])

        rows: list[dict[str, object]] = []
        for rec in key_frame.to_dict(orient="records"):
            sku = rec[cols.sku_id]
            dest = rec[cols.destination_id]
            key = (sku, dest)
            if key in stats.index and int(stats.loc[key, "count"]) >= min_periods:
                point: float | None = float(stats.loc[key, "mean"])
                status = ForecastStatus.OK.value
            else:
                point = None
                status = ForecastStatus.INSUFFICIENT_HISTORY.value
            for horizon, forecast_date in _horizon_dates(origin_ts, cfg.forecast.horizon_days):
                rows.append(
                    {
                        cols.sku_id: sku,
                        cols.destination_id: dest,
                        cols.forecast_origin: origin_ts,
                        cols.forecast_date: forecast_date,
                        cols.horizon_day: horizon,
                        cols.point_forecast: point,
                        cols.forecast_status: status,
                        cols.model_name: self.name,
                    }
                )
        result = pd.DataFrame(rows)
        return validate_forecast_frame(result, config=cfg).frame
