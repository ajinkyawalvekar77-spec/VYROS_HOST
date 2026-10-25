# Optiqo AI/ML engine

## FastAPI backend and Vercel

This repository also includes the Optiqo API integration in
`optiqo_backend/`. The Vercel-discoverable entry point is the repository-root
`main.py`, exporting the existing FastAPI application as `app`. For a Vercel
project created from this repository, set **Root Directory** to `.` (the
repository root); no `vercel.json` routing file is required. `.python-version`
selects Python 3.12, and `requirements.txt` includes both engine and API
dependencies.

For deployment, configure `VITE_API_BASE_URL` in Vercel as
`https://backend-vyros.onrender.com`. On Render, configure
`OPTIQO_CORS_ORIGINS=https://optiquo.vercel.app` and set `FIREBASE_PROJECT_ID`
to the actual Firebase project ID. The bundled engine is discovered relative
to the repository root by default; `OPTIQO_ENGINE_PATH` can override it. The
backend uses SQLite run records under `/tmp` when `VERCEL=1`; Vercel temporary
storage is not durable or shared across instances, so run history is not
persistent in production. Configure an external persistent store before
depending on run history.

The root `main.py` import and local API tests can verify application discovery
and local engine integration, but do not verify a Vercel deployment or its
native solver/forecast dependencies. Those require a Vercel build and runtime
smoke test.

Optiqo is a Python library for demand forecasting, batch eligibility, inventory
allocation, independent verification, explanations, and offline evaluation.
This directory is the `aiml` package root. The `optiqo_backend/` package
integrates the engine with FastAPI; the original separate backend checkout is
also maintained at `C:\Users\ajink\OneDrive\Desktop\optiqo-backend`.

## Implemented

- Strict validation for demand, inventory, lanes, costs, capacities, and
  forecast frames. Negative, non-finite, duplicate, missing, and invalid-schema
  values are rejected rather than repaired.
- Global chronological train/validation/test partitions and leakage-safe
  calendar, lag, rolling, and training-only group-mean features.
- Moving-average and seasonal-naive baselines, LightGBM training when its
  native runtime loads, MAE-based model selection, recursive forecasts, and
  residual-based uncertainty intervals.
- Batch/route/shelf-life eligibility and joint allocation across destinations
  sharing inventory.
- Lexicographic allocation: maximize demand served, minimize freight cost, then
  prefer earlier expiry when expiry evidence is available. Inventory, demand,
  shelf-life, route, and applicable capacity limits remain hard constraints.
- Independent plan verification, evidence-grounded explanations, allocation
  metrics, and a deterministic comparison with cheapest-first and FEFO-first
  policies.

No production accuracy or cost-saving claims are made. The validation metric
used for forecasting model selection is **MAE**; validation also reports WAPE
and signed bias. The test partition is kept separate and used only for
uncertainty residual calibration.

## Run tests

From this directory, with the package's parent on `PYTHONPATH` (the test
`conftest.py` sets this up):

```text
python -m pytest tests -q
```

`tests/test_end_to_end.py` runs deterministic synthetic demand through
forecasting, eligibility, allocation, independent verification, explanation,
and benchmarking. Core tests do not require live services or external data.

## Run the engine demo

The package root is this folder. From its parent directory, run the full
workflow on deterministic synthetic data:

```powershell
Set-Location C:\Users\ajink\OneDrive\Desktop
.\aiml\.venv\Scripts\python.exe -m aiml --demo
```

The command prints JSON containing the selected model, validation metrics,
forecast horizon, solver outcome, independent-check result, and benchmark
metrics. The data are synthetic and are not production results.

To launch the optional local desktop UI:

```powershell
Set-Location C:\Users\ajink\OneDrive\Desktop
.\aiml\.venv\Scripts\python.exe -m aiml --ui
```

The UI reads CSVs through the engine's configured column names. It accepts
demand history, inventory batches, permitted lanes, capacities, transport
costs, and held-out actual demand; the shelf-life CSV must contain
`sku_id,min_shelf_life_days`. Held-out dates must follow the latest history
date and fit within the configured forecast horizon. The UI displays forecast,
allocation, verification, explanation, and benchmark tables and can export the
selected table to CSV. The UI does not determine whether user-supplied CSV data
are synthetic or real.

## Environment notes

- Direct runtime and test dependencies are pinned in `requirements.txt` to the
  versions verified in the project venv.
- The project venv and the global interpreter are separate Python 3.15.0
  installs. Run commands with `.venv\Scripts\python.exe` to use the tested
  project dependencies.
- PuLP 4.x is supported through its `LpProblem.add_variable` API and the current
  solve-result object; older PuLP status-return APIs are also handled.
- A CBC executable must be discoverable by PuLP's `COIN_CMD`. In the audited
  local venv, CBC is provided by `cbcbox`; a direct known-optimum solve passed.
- A direct LightGBM import/train/predict check failed in both the project venv
  and global Python 3.15.0 because Windows could not load
  `lib_lightgbm.dll` or one of its dependencies. The specific dependency is
  unresolved, so Python-version compatibility is not established as the cause.
  Training reports the load failure and uses an identified baseline. See
  `ASSUMPTIONS.md`.
- The desktop UI uses the Python standard-library Tkinter and requires a
  graphical desktop session.

## Public entry points

- `aiml.forecasting.select_and_train` and
  `aiml.forecasting.forecast_seven_day`
- `aiml.optimization.eligible_shipments` and
  `aiml.optimization.optimize_allocation`
- `aiml.optimization.verify_allocation` and
  `aiml.optimization.explain_allocation`
- `aiml.evaluation.allocation_metrics` and
  `aiml.evaluation.run_benchmark`

Column names and the default seven-day horizon are configured through
`EngineConfig`. The column and business conventions remain proposals until
confirmed by the product/backend owners.

See [AUDIT_REPORT.md](./AUDIT_REPORT.md) for the implementation audit, evidence,
and remaining work.
