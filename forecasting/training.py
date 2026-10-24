
"""Chronological training, validation, and LightGBM model selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from ..config import EngineConfig
from ..exceptions import ValidationError
from ..schemas import validate_demand
from ..evaluation.forecast_metrics import mae, wape, bias
from .data_splitting import split_chronologically
from .features import LeakageSafeFeatureBuilder
from .model import train_lightgbm_model


@dataclass
class TrainingResult:
    """Artifacts and validation metrics from model selection."""

    model: Any
    feature_builder: LeakageSafeFeatureBuilder
    feature_columns: list[str]
    selected_params: dict[str, Any]
    validation_metrics: dict[str, float | None]
    validation_predictions: pd.DataFrame
    train_end: pd.Timestamp
    validation_end: pd.Timestamp
    model_name: str = "lightgbm"
    fallback_reason: str | None = None
    calibration_predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    model_validation_metrics: dict[str, dict[str, float | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class _LagFeatureModel:
    """Small estimator adapter used only when the LightGBM runtime is unavailable."""

    feature_name: str

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if self.feature_name not in features.columns:
            raise ValidationError(
                f"Baseline fallback requires feature {self.feature_name!r}."
            )
        values = pd.to_numeric(features[self.feature_name], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValidationError(
                f"Baseline fallback has insufficient history for {self.feature_name!r}."
            )
        return values.to_numpy(dtype=float)


def select_and_train(
    demand: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
    candidate_params: Sequence[Mapping[str, Any]] | None = None,
    random_state: int = 42,
) -> TrainingResult:
    """Select the lowest-MAE supported model using chronological validation.

    Features are constructed using past observations only. The feature
    builder's learned group means are fitted on the training partition only.

    Validation uses rolling one-step predictions: earlier observed validation
    demand may be used as a lag for a later validation date. This is not a
    fixed-origin, recursively generated seven-day evaluation.
    """
    cfg = config or EngineConfig()
    cols = cfg.columns
    date_col = cols.demand_date
    target_col = cols.quantity

    validated = validate_demand(demand, config=cfg).frame
    split = split_chronologically(validated, config=cfg, already_validated=True)

    # Fit learned feature statistics on training data only.
    builder = LeakageSafeFeatureBuilder(config=cfg)
    builder.fit(split.train, already_validated=True)

    # Lag and rolling values for each row use only earlier observations.
    featured = builder.transform(validated, already_validated=True)

    # IDs, dates and target values are not direct model features.
    excluded = {
        cols.sku_id,
        cols.destination_id,
        date_col,
        target_col,
    }
    feature_columns = [
        column for column in featured.columns if column not in excluded
    ]

    if not feature_columns:
        raise ValidationError("No usable forecasting features were created.")

    train_mask = featured[date_col] <= split.train_end
    validation_mask = (
        (featured[date_col] > split.train_end)
        & (featured[date_col] <= split.validation_end)
    )

    train_features = featured.loc[train_mask, feature_columns].copy()
    validation_features = featured.loc[
        validation_mask, feature_columns
    ].copy()

    y_train = featured.loc[train_mask, target_col].astype(float)
    y_validation = featured.loc[validation_mask, target_col].astype(float)

    # Remove rows without sufficient lag/rolling history.
    train_features = train_features.apply(pd.to_numeric, errors="raise").astype(float)
    validation_features = validation_features.apply(pd.to_numeric, errors="raise").astype(float)
    train_valid = ~np.isinf(train_features.to_numpy(dtype=float)).any(axis=1)
    validation_valid = ~np.isinf(validation_features.to_numpy(dtype=float)).any(axis=1)

    train_features = train_features.loc[train_valid]
    y_train = y_train.loc[train_valid]

    validation_features = validation_features.loc[validation_valid]
    y_validation = y_validation.loc[validation_valid]

    if train_features.empty:
        raise ValidationError(
            "No training rows remain after removing incomplete lag/rolling features. "
            "Provide more historical demand."
        )

    if validation_features.empty:
        raise ValidationError(
            "No validation rows remain after removing incomplete features. "
            "Provide more validation history or adjust the split."
        )

    if len(y_train) < 2:
        raise ValidationError("At least two usable training rows are required.")

    if y_validation.empty:
        raise ValidationError("Validation target is empty.")

    # A small, deterministic candidate set. Callers may provide their own.
    candidates = list(candidate_params) if candidate_params is not None else [
        {
            "n_estimators": 100,
            "learning_rate": 0.05,
            "num_leaves": 15,
        },
        {
            "n_estimators": 200,
            "learning_rate": 0.05,
            "num_leaves": 31,
        },
        {
            "n_estimators": 300,
            "learning_rate": 0.03,
            "num_leaves": 15,
        },
    ]

    if not candidates:
        raise ValueError("At least one LightGBM parameter candidate is required.")

    baseline_candidates = {
        f"calendar_lag_{cfg.forecast.seasonal_lag_days}": "seasonal_naive",
        f"calendar_rolling_mean_{cfg.forecast.moving_average_window_days}": (
            f"moving_average_{cfg.forecast.moving_average_window_days}"
        ),
    }
    baseline_candidates = {
        feature: name
        for feature, name in baseline_candidates.items()
        if feature in validation_features.columns
        and validation_features[feature].notna().all()
    }
    if baseline_candidates:
        comparable = validation_features[list(baseline_candidates)].notna().all(axis=1)
        validation_features = validation_features.loc[comparable]
        y_validation = y_validation.loc[comparable]

    best_model = None
    best_params: dict[str, Any] | None = None
    best_predictions: np.ndarray | None = None
    best_mae = float("inf")
    model_validation_metrics: dict[str, dict[str, float | None]] = {}
    best_lightgbm_mae = float("inf")

    def metrics_for(predictions: np.ndarray) -> dict[str, float | None]:
        actual_values = y_validation.to_numpy(dtype=float)
        return {
            "mae": mae(actual_values, predictions),
            "wape": wape(actual_values, predictions),
            "bias": bias(actual_values, predictions),
        }

    try:
        # Load once so a broken native runtime is distinguished from model errors.
        from lightgbm import LGBMRegressor as _LightGBMRuntimeCheck  # noqa: F401
    except (ImportError, OSError) as exc:
        if not baseline_candidates:
            raise ValidationError(
                "LightGBM is unavailable and no configured baseline has "
                "complete validation history."
            ) from exc
        if validation_features.empty:
            raise ValidationError(
                "LightGBM is unavailable and baseline fallback has "
                "insufficient validation history."
            ) from exc
        for feature, name in baseline_candidates.items():
            model = _LagFeatureModel(feature)
            predictions = np.maximum(model.predict(validation_features), 0.0)
            baseline_metrics = metrics_for(predictions)
            model_validation_metrics[name] = baseline_metrics
            score = float(baseline_metrics["mae"])
            if score < best_mae:
                best_model = model
                best_params = {"fallback_feature": feature}
                best_predictions = predictions
                best_mae = score
                model_name = name
        fallback_reason = str(exc)
    else:
        model_name = "lightgbm"
        fallback_reason = None
        for feature, name in baseline_candidates.items():
            model = _LagFeatureModel(feature)
            predictions = np.maximum(model.predict(validation_features), 0.0)
            baseline_metrics = metrics_for(predictions)
            model_validation_metrics[name] = baseline_metrics
            score = float(baseline_metrics["mae"])
            if score < best_mae:
                best_model = model
                best_params = {"fallback_feature": feature}
                best_predictions = predictions
                best_mae = score
                model_name = name
        for candidate in candidates:
            params = dict(candidate)

            model = train_lightgbm_model(
                train_features,
                y_train,
                params=params,
                random_state=random_state,
            )

            predictions = np.asarray(
                model.predict(validation_features),
                dtype=float,
            )

            if predictions.ndim != 1 or len(predictions) != len(y_validation):
                raise ValueError("Model returned an invalid validation prediction shape.")

            if not np.isfinite(predictions).all():
                raise ValueError("Model produced non-finite validation predictions.")

            # Demand forecasts cannot be negative.
            predictions = np.maximum(predictions, 0.0)
            candidate_metrics = metrics_for(predictions)
            score = float(candidate_metrics["mae"])

            if score < best_lightgbm_mae:
                best_lightgbm_mae = score
                model_validation_metrics["lightgbm"] = candidate_metrics
            if score < best_mae:
                best_mae = score
                best_model = model
                best_params = params
                best_predictions = predictions
                model_name = "lightgbm"

    if best_model is None or best_params is None or best_predictions is None:
        raise RuntimeError("No LightGBM candidate completed training successfully.")

    actual = y_validation.to_numpy()
    selected_mae = mae(actual, best_predictions)
    selected_wape = wape(actual, best_predictions)
    selected_bias = bias(actual, best_predictions)

    validation_output = featured.loc[
        validation_features.index,
        [cols.sku_id, cols.destination_id, date_col, target_col],
    ].copy()

    validation_output = validation_output.rename(
        columns={
            date_col: "forecast_date",
            target_col: "actual_demand",
        }
    )
    validation_output["predicted_demand"] = best_predictions
    validation_output["model_name"] = model_name

    test_mask = (
        (featured[date_col] > split.validation_end)
        & (featured[date_col] <= split.test_end)
    )
    calibration_features = featured.loc[test_mask, feature_columns].apply(
        pd.to_numeric, errors="raise"
    ).astype(float)
    calibration_actual = featured.loc[test_mask, target_col].astype(float)
    calibration_valid = ~np.isinf(calibration_features.to_numpy(dtype=float)).any(axis=1)
    if isinstance(best_model, _LagFeatureModel):
        calibration_valid &= calibration_features[best_model.feature_name].notna().to_numpy()
    calibration_features = calibration_features.loc[calibration_valid]
    calibration_actual = calibration_actual.loc[calibration_valid]
    calibration_predictions = np.asarray(best_model.predict(calibration_features), dtype=float)
    if not np.isfinite(calibration_predictions).all():
        raise ValidationError("Selected model produced non-finite calibration predictions.")
    calibration_predictions = np.maximum(calibration_predictions, 0.0)
    calibration_output = featured.loc[
        calibration_features.index,
        [cols.sku_id, cols.destination_id, date_col, target_col],
    ].copy()
    calibration_output = calibration_output.rename(
        columns={date_col: "forecast_date", target_col: "actual_demand"}
    )
    calibration_output["predicted_demand"] = calibration_predictions
    calibration_output["model_name"] = model_name

    return TrainingResult(
        model=best_model,
        feature_builder=builder,
        feature_columns=feature_columns,
        selected_params=best_params,
        validation_metrics={
            "mae": selected_mae,
            "wape": selected_wape,
            "bias": selected_bias,
        },
        validation_predictions=validation_output.reset_index(drop=True),
        train_end=split.train_end,
        validation_end=split.validation_end,
        model_name=model_name,
        fallback_reason=fallback_reason,
        calibration_predictions=calibration_output.reset_index(drop=True),
        model_validation_metrics=model_validation_metrics,
    )
