# Optiqo frontend

Responsive React/Vite application for Optiqo, the distribution intelligence
backend. The UI calls the existing FastAPI backend and does not implement
forecasting, risk scoring, or allocation algorithms in JavaScript.

## Requirements and install

- Node.js 22.12+ or 24+ (Vitest 5).
- npm compatible with the installed Node.js.
- Python environment and AI/ML engine dependencies as listed in the backend
  README.

```powershell
Set-Location C:\Users\ajink\OneDrive\Desktop\aiml\frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Vite serves the frontend at `http://127.0.0.1:5173`. Development requests to
`/api` are proxied to `http://127.0.0.1:8000`. Set `VITE_DEV_BACKEND_URL` in
`.env` to change this proxy destination. For a separately hosted frontend or
production build, `frontend/.env.production` sets
`VITE_API_BASE_URL=https://backend-vyros.onrender.com`. This is a public API
origin, not a secret. The same value should be configured in the Vercel
project's Environment Variables for Production. The production build does not
use Vite's development proxy. Backend CORS must allow the deployed origin
`https://optiquo.vercel.app`; set
`OPTIQO_CORS_ORIGINS=https://optiquo.vercel.app` in Render.

## Backend startup

In another PowerShell window:

```powershell
Set-Location C:\Users\ajink\OneDrive\Desktop\optiqo-backend
$python = "C:\Users\ajink\OneDrive\Desktop\aiml\.venv\Scripts\python.exe"
$env:OPTIQO_ENGINE_PATH = "C:\Users\ajink\OneDrive\Desktop\aiml"
$env:PYTHONPATH = "C:\Users\ajink\OneDrive\Desktop"
$env:FIREBASE_PROJECT_ID = "your Firebase project ID"
& $python -m uvicorn optiqo_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Backend installation and test instructions are in
`C:\Users\ajink\OneDrive\Desktop\optiqo-backend\README.md`.
The protected API routes remain locked until an authentication method is
connected to the frontend and compatible verified tokens can be provided.

## Build and tests

```powershell
npm run build
npm test
npm run preview
```

## API mapping

The service layer in `src/services/api.js` centralizes JSON requests,
timeouts, abort signals, backend error parsing, and downloads.

| Frontend operation | Verified backend route |
|---|---|
| API/engine connection | `GET /api/health` |
| Seeded dataset | `GET /api/demo-data?seed=…&profile=compact` |
| Dataset quality report | `POST /api/data/validate` |
| Active-dataset risk indicators | `POST /api/risk/dataset` |
| Forecast | `POST /api/forecast` |
| Plan, checker, explanations | `POST /api/plan` |
| Active-dataset, demo, or run-linked measures | `POST /api/risk/dataset`, `GET /api/risk?seed=…`, or `GET /api/risk?run_id=…` |
| Chronological policy replay | `POST /api/backtest` |
| Persisted run details | `GET /api/runs/{run_id}` |
| Run downloads | `GET /api/runs/{run_id}/export?format=json|csv` |

Request field names follow the backend Pydantic models. The demo loader uses
the actual backend data generator. Forecast model, solver status, checker
result, explanation, evaluation outputs, and exports come from the API. No
performance metrics or run results are synthesized by the frontend.

## Product pages

- Public responsive landing page and synthetic/illustrative-only product
  preview.
- Overview dashboard, data validation, risk indicators, distribution plan,
  recommendation evidence, chronological backtest, and persisted run detail.
- Light/dark theme toggle, responsive navigation, search and filters, status
  and error states, and downloadable backend run exports.
- The Data Validation page can download a backend-generated demo JSON file and
  upload JSON or CSV datasets (10 MiB frontend limit). JSON files containing
  the full engine tables are validated by the backend before forecasting.
  CSV files are for demand forecasting only and must contain exactly
  `sku_id`, `destination_id`, `demand_date` (`YYYY-MM-DD`), and `quantity`.
  The backend validates uploaded demand history with the `demand_only` scope
  before calling `POST /api/forecast`; invalid data are not forecast.
  Predictions,
  model/fallback information, and the persisted run reference are returned by
  the real backend engine and shown on the upload page and Overview. CSV
  uploads do not provide inventory, lanes, or capacities, so they cannot be
  used for allocation or full cross-table validation.
- The Risk Overview calculates indicators from the currently loaded dataset
  using the protected `POST /api/risk/dataset` route. It no longer silently
  prefers a stale prior backtest when a dataset is loaded. Results include
  forecast intervals and eligible network-stock comparisons only when the
  required source tables are available; no weighted risk score is generated.
- Allocation requires uploaded demand history plus non-empty inventory batches,
  eligible lanes, and transport costs. Backtesting additionally requires
  capacities and held-out `evaluation_actuals` for each selected evaluation
  day after `as_of`. The planning pages check these prerequisites before
  submitting, and direct users to upload a complete JSON dataset instead of
  sending an incomplete request or inventing missing operational data.

## Authentication status

The sign-in, registration, Google, verification, and password-reset screens
remain available outside local development. On `localhost`, `127.0.0.1`, or
`::1` in the Vite development server, `VITE_ENABLE_LOCAL_DEMO_ACCESS=true`
opens the workspace directly without displaying the sign-in page.

The backend still requires verified Firebase ID tokens for validation,
forecast, plan, backtest, run detail/export, and run-linked risk. Since the
frontend no longer acquires tokens, the local startup script enables
`OPTIQO_ALLOW_LOCAL_DEVELOPMENT_ACCESS=true`. The backend accepts protected
requests in that mode only when the direct client IP is loopback. This is a
local development convenience, not user authentication; do not bind or expose
the backend publicly while it is enabled. The backend flag defaults off.
Public health, demo-data, and seed-based demo-risk endpoints remain available.
No Firebase Web SDK configuration is required in the frontend environment file.

The backend also has no list-all-runs endpoint. Run history lists only run IDs
returned to this browser and stores those lightweight references in browser
storage; details are fetched from the persisted backend run endpoint. Pasting
a known run ID is also supported. Destination opening stock, landed cost,
margin, holding cost, and PRD-specific B1/B2 policy evaluation are absent from
the backend contract and are presented as unavailable or documented
limitations rather than invented UI values.

The engine currently reports its actual LightGBM fallback if the native
runtime is unavailable. The interface preserves that model and fallback
status without treating a fallback as LightGBM.

## Simple Windows startup

From the repository root, run `.\run-optiqo.ps1`. It creates `frontend/.env`
from the example only if that file does not exist, starts FastAPI and Vite in
separate terminals, waits for both health checks, and opens
`http://127.0.0.1:5173`. The launcher enables loopback-only development access
for protected API calls. Close the two server terminals to stop the services.
