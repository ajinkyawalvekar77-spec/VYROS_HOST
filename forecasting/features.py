"""Leakage-safe calendar, lag, and rolling features.

Rules:
- Calendar fields come only from the row's own date.
- Lags use ``shift`` within each series; they never read future rows.
- Rolling statistics are computed on values already shifted by one day so the
  current target is excluded.
- Any learned statistic (currently per-group mean) is fit on training rows only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from ..config import EngineConfig
from ..exceptions import LeakageError, ValidationError
from ..schemas import validate_demand


@dataclass
class LeakageSafeFeatureBuilder:
    config: EngineConfig = field(default_factory=EngineConfig)
    _fitted: bool = False
    _group_mean: pd.Series | None = None
    _train_end: pd.Timestamp | None = None

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, train: pd.DataFrame, *, already_validated: bool = False) -> "LeakageSafeFeatureBuilder":
        cfg = self.config
        frame = train if already_validated else validate_demand(train, config=cfg).frame
        keys = list(cfg.demand_group_columns())
        self._group_mean = frame.groupby(keys, sort=True)[cfg.columns.quantity].mean()
        self._train_end = pd.Timestamp(frame[cfg.columns.demand_date].max()).normalize()
        self._fitted = True
        return self

    def transform(self, frame: pd.DataFrame, *, already_validated: bool = False) -> pd.DataFrame:
        if not self._fitted or self._group_mean is None:
            raise ValidationError("Feature builder must be fit on training data before transform.")
        cfg = self.config
        cols = cfg.columns
        data = frame if already_validated else validate_demand(frame, config=cfg).frame
        data = data.sort_values(list(cfg.demand_group_columns()) + [cols.demand_date]).reset_index(drop=True)
        out = add_calendar_features(data, date_column=cols.demand_date)
        out = add_lag_features(
            out,
            group_columns=list(cfg.demand_group_columns()),
            date_column=cols.demand_date,
            value_column=cols.quantity,
            lags=cfg.forecast.lag_days,
        )
        out = add_calendar_lag_features(
            out,
            group_columns=list(cfg.demand_group_columns()),
            date_column=cols.demand_date,
            value_column=cols.quantity,
            lags=(cfg.forecast.seasonal_lag_days,),
        )
        out = add_rolling_features(
            out,
            group_columns=list(cfg.demand_group_columns()),
            date_column=cols.demand_date,
            value_column=cols.quantity,
            windows=cfg.forecast.rolling_windows_days,
        )
        out = add_calendar_moving_average_feature(
            out,
            group_columns=list(cfg.demand_group_columns()),
            date_column=cols.demand_date,
            value_column=cols.quantity,
            window_days=cfg.forecast.moving_average_window_days,
            min_periods=cfg.forecast.moving_average_min_periods,
        )
        means = self._group_mean.rename("train_group_mean").reset_index()
        out = out.merge(means, on=list(cfg.demand_group_columns()), how="left")
        return out

    def fit_transform(self, train: pd.DataFrame, *, already_validated: bool = False) -> pd.DataFrame:
        self.fit(train, already_validated=already_validated)
        return self.transform(train, already_validated=already_validated)


def add_calendar_features(frame: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    if date_column not in frame.columns:
        raise ValidationError("Date column missing for calendar features.", details={"column": date_column})
    out = frame.copy()
    dates = pd.to_datetime(out[date_column])
    out["calendar_dow"] = dates.dt.dayofweek.astype("int16")
    out["calendar_month"] = dates.dt.month.astype("int16")
    out["calendar_weekofyear"] = dates.dt.isocalendar().week.astype("int16")
    out["calendar_is_weekend"] = (out["calendar_dow"] >= 5).astype("int8")
    return out


def add_lag_features(
    frame: pd.DataFrame,
    *,
    group_columns: list[str],
    date_column: str,
    value_column: str,
    lags: tuple[int, ...],
) -> pd.DataFrame:
    _assert_sorted_within_groups(frame, group_columns, date_column)
    out = frame.copy()
    grouped = out.groupby(group_columns, sort=False)[value_column]
    for lag in lags:
        if lag < 1:
            raise LeakageError("Lag must be at least 1 to avoid using the current target.")
        out[f"lag_{lag}"] = grouped.shift(lag)
    return out


def add_calendar_lag_features(
    frame: pd.DataFrame,
    *,
    group_columns: list[str],
    date_column: str,
    value_column: str,
    lags: tuple[int, ...],
) -> pd.DataFrame:
    """Add exact calendar-date lags without bridging missing dates."""
    _assert_sorted_within_groups(frame, group_columns, date_column)
    out = frame.copy()
    dates = pd.to_datetime(out[date_column]).dt.normalize()
    indexed = out.assign(**{date_column: dates}).set_index(
        group_columns + [date_column]
    )[value_column]
    for lag in lags:
        if lag < 1:
            raise LeakageError("Calendar lag must be at least 1.")
        lookup_dates = dates - pd.Timedelta(days=lag)
        lookup_index = pd.MultiIndex.from_arrays(
            [out[column].to_numpy() for column in group_columns]
            + [lookup_dates.to_numpy()],
            names=group_columns + [date_column],
        )
        out[f"calendar_lag_{lag}"] = indexed.reindex(lookup_index).to_numpy()
    return out


def add_calendar_moving_average_feature(
    frame: pd.DataFrame,
    *,
    group_columns: list[str],
    date_column: str,
    value_column: str,
    window_days: int,
    min_periods: int,
) -> pd.DataFrame:
    """Compute the previous calendar-window mean, excluding each row's target."""
    _assert_sorted_within_groups(frame, group_columns, date_column)
    if window_days < 1 or min_periods < 1:
        raise LeakageError("Moving-average window and minimum periods must be positive.")
    out = frame.copy()
    output_column = f"calendar_rolling_mean_{window_days}"
    out[output_column] = float("nan")
    for _, group in out.groupby(group_columns, sort=False):
        dates = pd.to_datetime(group[date_column]).dt.normalize()
        values = pd.Series(
            pd.to_numeric(group[value_column], errors="raise").to_numpy(),
            index=pd.DatetimeIndex(dates),
        )
        means = values.rolling(
            f"{window_days}D",
            closed="left",
            min_periods=min_periods,
        ).mean()
        out.loc[group.index, output_column] = means.to_numpy()
    return out


def add_rolling_features(
    frame: pd.DataFrame,
    *,
    group_columns: list[str],
    date_column: str,
    value_column: str,
    windows: tuple[int, ...],
) -> pd.DataFrame:
    _assert_sorted_within_groups(frame, group_columns, date_column)
    out = frame.copy()
    for window in windows:
        if window < 1:
            raise LeakageError("Rolling window must be at least 1.")
        out[f"rolling_mean_{window}"] = np.nan
        out[f"rolling_std_{window}"] = np.nan

    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby(group_columns, sort=False):
        part = group.copy()
        shifted = part[value_column].shift(1)
        for window in windows:
            part[f"rolling_mean_{window}"] = shifted.rolling(window=window, min_periods=window).mean()
            part[f"rolling_std_{window}"] = shifted.rolling(window=window, min_periods=window).std()
        pieces.append(part)
    if not pieces:
        return out
    return pd.concat(pieces, axis=0).sort_index()


def _assert_sorted_within_groups(
    frame: pd.DataFrame,
    group_columns: list[str],
    date_column: str,
) -> None:
    if frame.empty:
        return
    dates = pd.to_datetime(frame[date_column])
    grouped = pd.DataFrame({"g": frame[group_columns].astype(str).agg("|".join, axis=1), "d": dates})
    if bool(grouped.duplicated(["g", "d"]).any()):
        raise LeakageError(
            "Duplicate dates within a series make lag/rolling order ambiguous.",
            details={"duplicate_count": int(grouped.duplicated(["g", "d"]).sum())},
        )
    previous_g = None
    previous_d = None
    for g, d in zip(grouped["g"].tolist(), grouped["d"].tolist()):
        if previous_g == g and d < previous_d:
            raise LeakageError("Rows must be sorted by date within each series before lag/rolling features.")
        previous_g, previous_d = g, d
