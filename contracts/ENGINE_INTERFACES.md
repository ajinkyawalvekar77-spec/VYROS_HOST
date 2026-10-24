# Proposed engine interfaces (discussion with Rahul)

**Status:** business/API proposal. Python entry points below are implemented,
but backend routes must not treat proposed payload names, units, or business
rules as confirmed until Rahul/product owners review them.

The AI/ML engine is a library. It does not own HTTP, auth, or persistence.

## 1. Shared types (proposed)

```text
ForecastStatus: ok | insufficient_history | prediction_failed | not_implemented

AllocationSolveStatus:
  optimal | feasible | infeasible | solver_unavailable | solver_failure

CheckerStatus:
  is_valid: boolean
  checks_passed, checks_failed: counts
  checks_not_run: list of reasons
```

Identifiers (`sku_id`, `destination_id`, `warehouse_id`, `batch_id`) are strings.

## 2. Validation and feature entry points (implemented)

These functions are the current library surface. Column names follow `EngineConfig.columns`.

```text
validate_demand(frame) -> ValidatedFrame
validate_inventory_batches(frame) -> ValidatedFrame
validate_lanes(frame) -> ValidatedFrame
validate_transport_costs(frame) -> ValidatedFrame
validate_capacities(frame) -> ValidatedFrame
validate_forecast_frame(frame) -> ValidatedFrame

split_chronologically(demand, *, config=None) -> ChronologicalSplit

LeakageSafeFeatureBuilder(config).fit(train).transform(frame)

SeasonalNaiveBaseline(config).fit(history).predict(origin=..., keys=None)
MovingAverageBaseline(config).fit(history).predict(origin=..., keys=None)
```

Errors: `SchemaError`, `ValidationError`, `SplitError`, `ConfigurationError`, `InsufficientHistoryError`, `LeakageError`.

Invalid rows are **not** auto-repaired. The backend should persist or display `details` from the exception rather than retrying with clipped quantities.

## 3. Forecasting (Python implementation available)

Implemented flow:

```text
select_and_train(demand_history, *, config=None, candidate_params=None)
  -> TrainingResult  # per-model validation MAE/WAPE/bias; test residuals for calibration

forecast_seven_day(
    history: DataFrame,
    training_result: TrainingResult,
    *,
    origin=None,
    config=None,
) -> DataFrame  # configured horizon; includes uncertainty fields
```

The model selector compares LightGBM, seasonal-naive, and moving-average
features on shared validation rows using MAE. If LightGBM's native runtime
cannot load, the selected baseline is named truthfully and its load failure is
retained in `TrainingResult.fallback_reason`. Test-period residuals are used
for marginal interval calibration.

Business/API questions still open for Rahul:

1. Is the grain of demand `sku × destination × day`?
2. Are destinations stores, regions, or customers?
3. What is the production `as_of` / origin clock (UTC date, warehouse local date)?
4. Should the backend send a pre-filtered history window or the full series?
5. File format in/out: parquet, CSV, JSON records, Arrow?
6. Where should artifacts be written (`artifacts/` vs backend object storage)?

## 4. Allocation (Python implementation available)

Implemented flow:

```text
eligible_shipments(inventory_batches, lanes, sku_min_shelf_life_days, *,
                   origin_date, config=None) -> DataFrame

optimize_allocation(eligible, inventory_batches, capacities=None,
                    demand_forecast=None, transport_costs=None, *,
                    config=None, solver=None, time_limit_seconds=60,
                    as_of=None) -> AllocationResult
```

Proposed `AllocationResult` fields (not frozen):

- `status` (`optimal`, `feasible`, `infeasible`, `solver_unavailable`,
  `solver_failure`)
- `plan` (populated only when the solver reports an optimal or feasible
  solution)
- `objective_value` (only when the solver produced one)
- `solver_status_code`, `constraints_added`, and structured `diagnostics`

The objective is lexicographic: maximize total demand served, minimize freight,
then prefer earlier expiry when expiry data exists. Holding, expiry-loss, and
unmet-demand monetary penalties are omitted until approved input parameters
exist. Shipment quantities are continuous pending confirmation of unit
discreteness.

Business/API questions still open for Rahul:

1. Shipment grain: `batch × destination`, `warehouse × sku × destination`, or other?
2. Are capacities per destination per day, per week, or per SKU?
3. Holding / expiry / unmet-demand penalty weights and units?
4. Must remaining shelf life on arrival be ≥ some minimum? What field carries that minimum?
5. Can a batch ship to multiple destinations in one run?
6. Who invokes CBC, and is a solver binary allowed in this environment?

## 5. Independent verification (Python implementation available)

```text
verify_allocation(allocation, inventory, lanes, capacities, as_of, config)
  -> AllocationCheckResult
```

The implemented checker takes the proposed plan, eligible candidates, original
inventory, optional capacities and demand, plus optional original lanes,
`as_of`, and SKU minimums. It reports `checks_not_run` when route/shelf-life
inputs are omitted, and `is_valid` remains false until all required checks run.
The backend should refuse to apply shipments unless the checker passes all
required checks.

`explain_allocation` returns evidence rows for all candidates, including zero
allocations. It reports evidence without assigning unsupported causal reasons.

## 6. Evaluation (Python implementation available)

`allocation_metrics` reports held-out service/unmet demand, expiry waste when
expiry evidence exists, and freight when transport costs are supplied.
`run_benchmark` compares the optimizer against cheapest-first and FEFO-first
greedy policies using the same forecast-based caps, candidates, inventory,
capacity, and costs. Actual demand must be dated after `as_of` within the
configured horizon. Monetary totals include freight only until other penalty
inputs are defined.

## 7. What this engine will not do

- HTTP routes, auth, job queues, or database writes
- Silent data repair
- Claiming LightGBM superiority without a measured validation comparison
- Claiming cost savings as real-world results
