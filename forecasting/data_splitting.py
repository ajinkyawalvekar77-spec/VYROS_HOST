"""Chronological train / validation / test splits without temporal leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..config import EngineConfig, SplitConfig
from ..exceptions import ConfigurationError, SplitError, ValidationError
from ..schemas import validate_demand


@dataclass(frozen=True)
class ChronologicalSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    train_end: pd.Timestamp
    validation_end: pd.Timestamp
    test_end: pd.Timestamp
    date_column: str

    def assert_no_overlap(self) -> None:
        partitions = {
            "train": set(self.train[self.date_column]),
            "validation": set(self.validation[self.date_column]),
            "test": set(self.test[self.date_column]),
        }
        overlap_tv = partitions["train"] & partitions["validation"]
        overlap_tt = partitions["train"] & partitions["test"]
        overlap_vt = partitions["validation"] & partitions["test"]
        if overlap_tv or overlap_tt or overlap_vt:
            raise SplitError(
                "Split partitions share demand dates.",
                details={
                    "train_validation": sorted(overlap_tv)[:10],
                    "train_test": sorted(overlap_tt)[:10],
                    "validation_test": sorted(overlap_vt)[:10],
                },
            )


def _as_timestamp(value: date | pd.Timestamp | str, *, name: str) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value).normalize()
    except (TypeError, ValueError) as exc:
        raise SplitError(f"Could not parse {name}.", details={"value": repr(value)}) from exc
    if pd.isna(ts):
        raise SplitError(f"{name} is missing.", details={"value": repr(value)})
    return ts


def _cutoffs_from_unique_dates(
    unique_dates: pd.DatetimeIndex,
    split: SplitConfig,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    n = len(unique_dates)
    if n < split.min_unique_dates:
        raise SplitError(
            "Not enough unique dates to form train/validation/test partitions.",
            details={"unique_dates": n, "min_unique_dates": split.min_unique_dates},
        )
    total = split.train_fraction + split.validation_fraction + split.test_fraction
    if abs(total - 1.0) > 1e-9:
        raise ConfigurationError(
            "Split fractions must sum to 1.0.",
            details={
                "train_fraction": split.train_fraction,
                "validation_fraction": split.validation_fraction,
                "test_fraction": split.test_fraction,
                "sum": total,
            },
        )
    if min(split.train_fraction, split.validation_fraction, split.test_fraction) <= 0:
        raise ConfigurationError("Each split fraction must be positive.")

    train_count = max(1, int(n * split.train_fraction))
    remaining = n - train_count
    val_count = max(1, int(n * split.validation_fraction))
    if val_count >= remaining:
        val_count = max(1, remaining - 1)
    test_count = n - train_count - val_count
    if test_count < 1:
        raise SplitError(
            "Fraction rounding left an empty test partition. Provide explicit cutoff dates.",
            details={"unique_dates": n, "train_count": train_count, "validation_count": val_count},
        )
    train_end = unique_dates[train_count - 1]
    validation_end = unique_dates[train_count + val_count - 1]
    test_end = unique_dates[-1]
    return train_end, validation_end, test_end


def split_chronologically(
    demand: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
    already_validated: bool = False,
) -> ChronologicalSplit:
    """Split demand by calendar date.

    Train contains dates ``<= train_end``.
    Validation contains ``train_end < date <= validation_end``.
    Test contains ``validation_end < date <= test_end``.

    Rows are never shuffled. Features that look at the future of a row's date
    are not created here; see ``forecasting.features``.
    """
    cfg = config or EngineConfig()
    split_cfg = cfg.split
    date_col = cfg.columns.demand_date
    frame = demand if already_validated else validate_demand(demand, config=cfg).frame
    if date_col not in frame.columns:
        raise ValidationError("Demand date column is missing after validation.")

    unique_dates = pd.DatetimeIndex(sorted(frame[date_col].drop_duplicates()))
    if split_cfg.train_end is not None or split_cfg.validation_end is not None:
        if split_cfg.train_end is None or split_cfg.validation_end is None:
            raise ConfigurationError(
                "When using explicit cutoffs, both train_end and validation_end are required."
            )
        train_end = _as_timestamp(split_cfg.train_end, name="train_end")
        validation_end = _as_timestamp(split_cfg.validation_end, name="validation_end")
        test_end = (
            _as_timestamp(split_cfg.test_end, name="test_end")
            if split_cfg.test_end is not None
            else unique_dates[-1]
        )
    else:
        train_end, validation_end, test_end = _cutoffs_from_unique_dates(unique_dates, split_cfg)

    if not (train_end < validation_end < test_end):
        raise SplitError(
            "Cutoffs must satisfy train_end < validation_end < test_end.",
            details={
                "train_end": str(train_end.date()),
                "validation_end": str(validation_end.date()),
                "test_end": str(test_end.date()),
            },
        )
    min_date = unique_dates[0]
    max_date = unique_dates[-1]
    if train_end < min_date or test_end > max_date or train_end >= max_date:
        raise SplitError(
            "Cutoffs fall outside the observed demand date range.",
            details={
                "min_date": str(min_date.date()),
                "max_date": str(max_date.date()),
                "train_end": str(train_end.date()),
                "test_end": str(test_end.date()),
            },
        )

    train = frame.loc[frame[date_col] <= train_end].copy()
    validation = frame.loc[(frame[date_col] > train_end) & (frame[date_col] <= validation_end)].copy()
    test = frame.loc[(frame[date_col] > validation_end) & (frame[date_col] <= test_end)].copy()
    leftover = frame.loc[frame[date_col] > test_end]
    if len(leftover) > 0:
        raise SplitError(
            "Some rows fall after test_end and would be dropped silently. Refusing the split.",
            details={"dropped_rows": int(len(leftover)), "test_end": str(test_end.date())},
        )
    if len(train) == 0 or len(validation) == 0 or len(test) == 0:
        raise SplitError(
            "A split partition is empty.",
            details={
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                "test_rows": int(len(test)),
            },
        )

    result = ChronologicalSplit(
        train=train.reset_index(drop=True),
        validation=validation.reset_index(drop=True),
        test=test.reset_index(drop=True),
        train_end=train_end,
        validation_end=validation_end,
        test_end=test_end,
        date_column=date_col,
    )
    result.assert_no_overlap()
    if result.train[date_col].max() > train_end:
        raise SplitError("Train partition contains dates after train_end.")
    if result.validation[date_col].min() <= train_end:
        raise SplitError("Validation partition contains dates on or before train_end.")
    if result.test[date_col].min() <= validation_end:
        raise SplitError("Test partition contains dates on or before validation_end.")
    return result
