
"""Generate recursive seven-day demand forecasts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..config import EngineConfig
from ..exceptions import ValidationError
from ..schemas import ForecastStatus, validate_demand, validate_forecast_frame
from .uncertainty import estimate_uncertainty


def forecast_seven_day(
    history: pd.DataFrame,
    training_result: Any,
    *,
    origin: pd.Timestamp | str | None = None,
    config: EngineConfig | None = None,
) -> pd.DataFrame:
    """Generate a recursive forecast for each SKU-destination series.

    Parameters
    ----------
    history:
        Historical demand containing sku_id, destination_id, demand_date,
        and quantity columns.
    training_result:
        Result returned by select_and_train(), containing model,
        feature_builder, and feature_columns.
    origin:
        Forecast cutoff date. Defaults to the latest date in history.
    config:
        Optional engine configuration. Defaults to the fitted feature
        builder's configuration.

    Returns
    -------
    pandas.DataFrame
        A validated forecast frame with one row per series and forecast day.
    """
    if training_result is None:
        raise ValueError("training_result must be supplied.")

    for attribute in ("model", "feature_builder", "feature_columns"):
        if not hasattr(training_result, attribute):
            raise ValueError(
                f"training_result is missing required attribute: {attribute}"
            )

    builder = training_result.feature_builder

    if not getattr(builder, "fitted", False):
        raise ValidationError("The feature builder must be fitted before forecasting.")

    cfg = config or builder.config
    cols = cfg.columns

    if config is not None and config != builder.config:
        raise ValueError(
            "config must match the configuration used to fit the feature builder."
        )

    validated = validate_demand(history, config=cfg).frame
    validated[cols.demand_date] = pd.to_datetime(
        validated[cols.demand_date]
    ).dt.normalize()

    if origin is None:
        origin_ts = validated[cols.demand_date].max()
    else:
        origin_ts = pd.Timestamp(origin).normalize()

    # Never allow observations after the forecast origin into the forecast.
    observed = validated.loc[
        validated[cols.demand_date] <= origin_ts
    ].copy()

    if observed.empty:
        raise ValidationError("No historical demand exists at or before origin.")

    model = training_result.model
    feature_columns = list(training_result.feature_columns)

    if not feature_columns:
        raise ValidationError("The training result contains no feature columns.")

    group_columns = list(cfg.demand_group_columns())
    keys = observed[group_columns].drop_duplicates().reset_index(drop=True)

    # Create future rows for all known series. Their quantities are placeholders
    # until predicted, and are replaced one day at a time below.
    future_rows: list[dict[str, Any]] = []
    horizon_days = cfg.forecast.horizon_days

    for record in keys.to_dict(orient="records"):
        for horizon in range(1, horizon_days + 1):
            row = {
                cols.sku_id: record[cols.sku_id],
                cols.destination_id: record[cols.destination_id],
                cols.demand_date: origin_ts + pd.Timedelta(days=horizon),
                cols.quantity: 0.0,
            }
            future_rows.append(row)

    future = pd.DataFrame(future_rows)
    future[cols.demand_date] = pd.to_datetime(future[cols.demand_date])

    # Keep an index so each recursive prediction can be written back safely.
    future["_forecast_horizon"] = (
        (future[cols.demand_date] - origin_ts).dt.days.astype(int)
    )

    predictions_by_index: dict[int, float] = {}

    for horizon in range(1, horizon_days + 1):
        # Previous future-day quantities now contain predictions. The current
        # day's target is excluded from its own lag and rolling features.
        combined = pd.concat(
            [
                observed,
                future.drop(columns=["_forecast_horizon"]),
            ],
            ignore_index=True,
        )

        featured = builder.transform(combined)

        current_date = origin_ts + pd.Timedelta(days=horizon)
        current_mask = featured[cols.demand_date].eq(current_date)
        current = featured.loc[current_mask].copy()

        if len(current) != len(keys):
            raise ValidationError(
                f"Expected {len(keys)} rows for forecast day {horizon}, "
                f"but found {len(current)}."
            )

        X = current.reindex(columns=feature_columns)

        # Convert nullable numeric columns to values LightGBM can consume.
        for column in X.columns:
            X[column] = pd.to_numeric(X[column], errors="raise")

        raw_predictions = np.asarray(model.predict(X), dtype=float)

        if raw_predictions.ndim != 1 or len(raw_predictions) != len(current):
            raise ValidationError("The model returned an invalid prediction shape.")

        if not np.isfinite(raw_predictions).all():
            raise ValidationError("The model returned non-finite predictions.")

        day_predictions = np.maximum(raw_predictions, 0.0)

        # Save this day's predicted quantity into the matching future row.
        for (_, current_row), value in zip(current.iterrows(), day_predictions):
            sku = current_row[cols.sku_id]
            destination = current_row[cols.destination_id]

            match = (
                future[cols.demand_date].eq(current_date)
                & future[cols.sku_id].eq(sku)
                & future[cols.destination_id].eq(destination)
            )

            matched_indices = future.index[match]
            if len(matched_indices) != 1:
                raise ValidationError(
                    "Could not uniquely match a future forecast row to its series."
                )

            future.loc[matched_indices[0], cols.quantity] = float(value)
            predictions_by_index[int(matched_indices[0])] = float(value)

    output_rows: list[dict[str, Any]] = []

    for index, row in future.iterrows():
        horizon = int(row["_forecast_horizon"])

        output_rows.append(
            {
                cols.sku_id: row[cols.sku_id],
                cols.destination_id: row[cols.destination_id],
                cols.forecast_origin: origin_ts,
                cols.forecast_date: row[cols.demand_date],
                cols.horizon_day: horizon,
                cols.point_forecast: predictions_by_index[int(index)],
                cols.forecast_status: ForecastStatus.OK.value,
                cols.model_name: getattr(training_result, "model_name", "lightgbm"),
            }
        )

    result = pd.DataFrame(output_rows)
    result = validate_forecast_frame(result, config=cfg).frame
    calibration = getattr(training_result, "calibration_predictions", pd.DataFrame())
    if calibration.empty:
        result[cols.lower_bound] = np.nan
        result[cols.upper_bound] = np.nan
        result[cols.interval_width] = np.nan
        result[cols.uncertainty_status] = "insufficient_residuals"
    else:
        intervals = estimate_uncertainty(
            calibration["actual_demand"].to_numpy(dtype=float),
            calibration["predicted_demand"].to_numpy(dtype=float),
            result[cols.point_forecast].to_numpy(dtype=float),
            confidence_level=cfg.forecast.uncertainty_confidence_level,
            min_samples=cfg.forecast.min_uncertainty_residuals,
        )
        result[cols.lower_bound] = intervals["lower_bound"].to_numpy()
        result[cols.upper_bound] = intervals["upper_bound"].to_numpy()
        result[cols.interval_width] = intervals["interval_width"].to_numpy()
        result[cols.uncertainty_status] = intervals["uncertainty_status"].to_numpy()
    return validate_forecast_frame(result, config=cfg).frame
