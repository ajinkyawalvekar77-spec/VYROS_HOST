# Assumptions (Task 1)

Nothing below is confirmed backend or business truth. Treat every item as a proposal until Rahul (backend) and product confirm it.

## Layout

- This workspace folder **is** the Python package root. Files live here (`config.py`, `forecasting/`, …) rather than in a nested `aiml/aiml/` directory.
- Imports are `import aiml...` with the parent of this folder on `sys.path` (see `tests/conftest.py`).

## Proposed column names

Configured in `ColumnMap` (`config.py`) so they can be renamed in one place.

| Domain | Required columns | Optional columns |
| --- | --- | --- |
| Historical demand | `sku_id`, `destination_id`, `demand_date`, `quantity` | |
| Inventory batches | `batch_id`, `sku_id`, `warehouse_id`, `quantity` | `expiry_date`, `received_date`, `remaining_shelf_life_days` |
| Lanes | `warehouse_id`, `destination_id`, `is_available` | `transit_days` |
| Transport costs | `warehouse_id`, `destination_id`, `unit_transport_cost` | `sku_id` (if absent, cost is lane-level for all SKUs) |
| Capacities | `destination_id`, `capacity_units` | `sku_id`, `warehouse_id`, `effective_date` |
| Forecast output | `sku_id`, `destination_id`, `forecast_origin`, `forecast_date`, `horizon_day`, `point_forecast`, `forecast_status`, `model_name` | |

Business keys used for duplicate detection:

- Demand: `(sku_id, destination_id, demand_date)`
- Batches: `(batch_id)`
- Lanes: `(warehouse_id, destination_id)`
- Costs: lane keys, plus `sku_id` when present
- Capacities: destination, plus any optional grain columns that are present

## Units

- `quantity`, `capacity_units`, and `point_forecast` are in native SKU units (not confirmed: cases, eaches, kg, …).
- `unit_transport_cost` is currency per quantity unit. Currency code is unknown.
- `transit_days` and `remaining_shelf_life_days` are whole days.
- `horizon_day` is 1..7, where 1 is the calendar day after `forecast_origin`.

## Validation policy

- Negative demand or negative on-hand is an error. Values are **not** clipped to zero.
- Zero demand and zero on-hand are valid.
- Expired batches remain valid *records*. They must not be allocated later.
- Unavailable lanes remain valid *records*. They must not be used later.
- Duplicates fail validation. Competing rows are not aggregated.
- Unparseable dates fail validation. Time-of-day, if present, is normalized to midnight; timezone is not assumed.
- Empty identifier strings after stripping are invalid.
- Empty frames are invalid for required inputs.

## Splitting and features

- Partitions are global by calendar date, shared across all series.
- Default fractions are 70% / 15% / 15% of unique dates, used only when explicit cutoffs are omitted.
- Lag `k` is demand `k` observations earlier in the dated series after sorting. Gaps are not interpolated; the lag is a positional shift, which matches a calendar lag only when the series is daily and complete.
- Rolling windows run on values **shifted by one**, so the current target is excluded. Incomplete windows are `NA` (`min_periods=window`).
- `train_group_mean` is the only learned statistic in Task 1 and is computed from training rows only. Unseen groups get `NA`.

## Baselines

- Seasonal naive: \(\hat{y}_{d} = y_{d-7}\) when that date exists on or before the origin. Otherwise `insufficient_history`.
- 28-day moving average: mean of observations in `[origin - 27 days, origin]`. If the observation count is below 28, status is `insufficient_history` (the window is not silently shortened).
- Both methods emit a 7-day horizon from the origin. The moving-average value is repeated across the horizon (open-loop from a single origin).
- During rolling one-step model comparison, moving-average features are computed from prior observations only; if that model is selected, recursive forecasting updates the trailing window with earlier predictions.
- Zero is a legitimate observation and may be forecast.

## Forecast evaluation and uncertainty

- Model selection compares supported models on the same validation rows and
  chooses the lowest MAE. MAE is in native demand units; WAPE is a ratio and is
  undefined when total actual demand is zero; bias is prediction minus actual.
- Available candidates are LightGBM, seasonal naive, and moving average when
  their configured features have adequate history. If LightGBM cannot load,
  the selected baseline name and load failure reason are retained; baseline
  forecasts are never labeled LightGBM.
- The chronological test partition is not used for model selection. Its
  one-step residuals calibrate marginal symmetric intervals pooled across
  series. Insufficient residuals produce null bounds and
  `insufficient_residuals`; coverage is not guaranteed per series or horizon.

## Optimization, checking, and evaluation

- Allocation decision quantities are continuous because native quantity
  units/discreteness are not confirmed. Confirm units and require integer
  shipments before production use if fractional quantities are invalid.
- The optimizer uses lexicographic priorities: maximize total demand served
  within forecast caps, minimize freight cost, then prefer earlier expiry when
  expiry evidence exists. Freight is currency per quantity unit. No synthetic
  reward coefficient or unapproved monetary penalty is used.
- Unmet-demand penalties, expiry-loss cost, and holding cost are not modeled:
  the input contract supplies no values/weights. The benchmark reports
  service/unmet demand, eligible inventory expiring within the horizon, and
  freight when supported; modeled monetary total includes freight only.
- Capacity rows apply at their supplied destination/SKU/warehouse grain. If
  `effective_date` exists, the latest row on or before `as_of` applies.
  Overlapping or ambiguous capacities are rejected, not summed.
- Lane eligibility requires transit time and expiry or remaining-life evidence.
  Arrival shelf life must meet the supplied SKU minimum. Minimums and capacity
  period semantics remain proposed business rules.
- The checker verifies candidate and inventory identity/totals, demand, and
  capacity. It verifies route availability and arrival shelf life when original
  lanes, `as_of`, and SKU minimums are supplied, and reports checks it could
  not run.
- Benchmark actuals must have demand dates strictly after `as_of` and within
  the configured horizon; they are used only for evaluation. Forecast limits
  and all other candidate inputs are shared across policies. A caller can
  still mislabel data provenance, which cannot be proven by date checks alone.

## Environment

- Audited local `.venv`: **Python 3.15.0**, pandas 3.1.0, NumPy 2.5.4, PuLP
  4.2.0, and pytest installed. `cbcbox` supplies the CBC executable used by
  PuLP `COIN_CMD`.
- The global interpreter and project `.venv` are separate Python 3.15.0
  installations. Use the project venv for the commands documented in
  `README.md`.
- LightGBM 4.7.0 is installed in the project venv and globally. A direct,
  unmocked import/train/predict attempt failed in both with Windows
  `FileNotFoundError`: `lib_lightgbm.dll` or one of its dependencies could not
  load. The transitive DLL has not been identified; the available evidence
  does not establish that Python 3.15 itself is the cause. LightGBM training
  has not been claimed as successful. The explicit baseline fallback is tested.
- CBC-backed allocation and the deterministic end-to-end test have been run
  locally against the PuLP 4.2 API. A separate direct CBC test solved a
  two-variable linear program at its known optimum.
- The standard-library Tkinter UI is implemented for desktop sessions. A
  graphical UI interaction test was not run in this environment.
