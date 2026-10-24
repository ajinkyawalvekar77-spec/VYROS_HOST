# Optiqo engine audit

## Scope and evidence

The workspace is the Python package root; there is no nested `aiml/aiml`
package, frontend, backend service, or separate PRD in this workspace. The
available requirements are the README, `ASSUMPTIONS.md`, and
`contracts/ENGINE_INTERFACES.md`. The source audit covered project
configuration, schemas, exceptions, forecasting, optimization, evaluation,
and the tests. The complete source/test inventory is listed below.

## Findings

| Feature | Current implementation and evidence | Remaining work / limitation | Priority | Proposed next step |
|---|---|---|---|---|
| Data validation and contracts | Configurable columns and strict validators cover demand, inventory, lanes, costs, capacities, and forecasts; `tests/test_validation.py` exercises invalid values and schema failures. | Proposed business column names and units have not been confirmed by product/backend owners. | High before integration | Confirm grain, units, and names before binding backend payloads. |
| Chronological splitting and features | Global date cutoffs, explicit cutoff validation, leakage-safe lag/rolling features, calendar baseline features, and training-only group statistics are implemented. `tests/test_data_splitting.py` and `tests/test_features.py` cover chronology, gaps, and leakage behavior. | Default partitions are date-based and not series-stratified; sparse series may have insufficient model features. | Medium | Confirm the global split policy and sparse-series behavior with product. |
| Forecast training and metrics | Validation-only model selection compares LightGBM and documented baselines; MAE/WAPE/bias are reported. Recursive seven-day forecasts and test-residual intervals have explicit insufficient-history states. `tests/test_forecasting.py`, `tests/test_forecast_metrics.py`, and `tests/test_uncertainty.py` cover these paths. | Native LightGBM runtime could not be loaded on either installed Python 3.15 Windows interpreter; the best available baseline is used instead. | High for LightGBM deployment | Resolve the Windows native DLL dependency and repeat direct import/train/predict on the deployment environment. |
| Eligibility and allocation | Batch/route/shelf-life eligibility feeds a joint-stock PuLP model with demand and capacity constraints, freight minimization, FEFO tie-breaking, and explicit solver outcomes. `tests/test_eligibility.py` and `tests/test_optimizer.py` include deterministic constraints. | Shipments are continuous because native units are unconfirmed. Unmet-demand, expiry-loss, and holding-cost weights are not supplied. | High before production allocation | Confirm quantity discreteness and objective cost inputs; do not invent values. |
| Independent verification | Checker recomputes plan, stock, demand, capacity, lane, and shelf-life conditions when required source inputs are provided; missing checks prevent a valid result. `tests/test_checker.py` includes deliberately invalid plans. | The backend must provide original lanes, origin, and SKU minimum shelf-life data to run all route checks. | High before applying a plan | Make complete verifier input mandatory at the backend shipment-application boundary. |
| Explanations | Explanation rows derive from plan, candidate, stock, capacity, demand, and cost data; unsupported causal claims are avoided. `tests/test_end_to_end.py` checks evidence values. | Explanation language is limited to available input evidence. | Low | Extend only after backend exposes additional evidence fields. |
| Benchmarking | Optimizer, cheapest-first, and FEFO-first policies use common forecast caps, candidates, capacity, costs, and held-out dates. `tests/test_benchmark.py` checks deterministic behavior. | Benchmark outputs are assumption-dependent and cannot establish real-world savings. Actual-data provenance cannot be proven by date checks. | Medium | Supply a governed held-out evaluation set and label its provenance. |
| End-to-end entry point | `demo.py` calls the public engine functions for a full deterministic synthetic path; `python -m aiml --demo` exposes it. `tests/test_demo.py` and `tests/test_end_to_end.py` verify the workflow. | Synthetic results are not production metrics or forecasts. | Medium | Keep synthetic demo isolated and replace its data only with approved sample inputs. |
| Local demo UI | Optional Tkinter UI selects CSV inputs, displays forecast/allocation/checks/explanations/benchmark tables, and exports the selected table. It calls the same `run_demo_workflow` as the CLI. | Requires a graphical desktop. Automated UI interaction was not run; uploaded CSV provenance is user-supplied. | Low | Perform manual desktop acceptance testing and confirm input-column contract. |
| Runtime and solver | Project `.venv` uses Python 3.15.0, pandas 3.1.0, NumPy 2.5.4, PuLP 4.2.0, and CBC from `cbcbox`. A direct CBC known-optimum LP solve succeeded. | LightGBM native dependency remains unresolved. Python 3.15 is not proven to be the cause, and no alternate interpreter is installed here. | High for deployment | Diagnose the native loader dependency on the deployment machine; record a supported runtime only after an actual train/predict check. |

## Inspected source and tests

- Root: `config.py`, `schemas.py`, `exceptions.py`, `__init__.py`,
  `requirements.txt`, and `pytest.ini`.
- Forecasting: all Python modules in `forecasting/`, including
  `data_splitting.py`.
- Optimization: all Python modules in `optimization/`.
- Evaluation: all Python modules in `evaluation/`.
- Tests: all Python modules in `tests/`.
- Documentation/contracts: `README.md`, `ASSUMPTIONS.md`, and
  `contracts/ENGINE_INTERFACES.md`.
- Workspace inventory: `artifacts/` contains only `.gitkeep`; no sample data or
  existing frontend/backend application was found in this workspace.

## Runtime facts

- The project venv and global Python are separate Python 3.15.0 installs.
- Full project test suite after this audit's changes: **53 passed, 0 failed,
  0 skipped**.
- CBC was available and solved `max 3x + 2y` subject to `x + y <= 4`, `x <= 2`,
  `x,y >= 0` at the known optimum `(x,y) = (2,2)`, objective `10`.
- LightGBM direct import failed before estimator construction in both
  interpreters with a DLL load `FileNotFoundError`; no LightGBM prediction or
  training result is available.
- No business-cost weights or integer-quantity requirement were added without
  an approved contract.
