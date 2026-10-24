"""FastAPI application for integrating Optiqo engine operations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .auth import (
    AuthenticatedUser,
    optional_verified_user,
    require_verified_user,
)
from .config import get_settings
from .demo_data import generate_demo_data
from .engine_adapter import (
    EngineUnavailableError,
    engine_readiness,
    run_forecast,
    run_plan,
)
from .risk import dataset_supply_risks, demo_supply_risks
from .run_store import create_run, finish_run, get_run
from .schemas import (
    BacktestRequest,
    BacktestResponse,
    DataValidateRequest,
    DatasetPayload,
    ForecastRequest,
    ForecastResponse,
    HealthResponse,
    PlanRequest,
    PlanResponse,
    RunRecord,
)
from .simulation import run_backtest
from .validation import validate_dataset

logger = logging.getLogger("optiqo_backend")
settings = get_settings()

app = FastAPI(
    title="Optiqo Backend API",
    version="0.1.0",
    description="API orchestration for the existing Optiqo forecasting and allocation engine.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def enforce_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            return _error_response(
                400, "invalid_content_length", "Content-Length must be an integer."
            )
        if size > settings.max_request_bytes:
            return _error_response(
                413,
                "request_too_large",
                f"Request exceeds the {settings.max_request_bytes}-byte limit.",
            )
    return await call_next(request)


def _error_response(
    status_code: int, code: str, message: str, details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "Invalid value."),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return _error_response(
        422,
        "request_validation_error",
        "The request body or query parameters are invalid.",
        errors,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    _request: Request, exc: HTTPException
) -> JSONResponse:
    if isinstance(exc.detail, dict) and {"code", "message"}.issubset(exc.detail):
        return _error_response(
            exc.status_code,
            str(exc.detail["code"]),
            str(exc.detail["message"]),
            exc.detail.get("details"),
            exc.headers,
        )
    return _error_response(
        exc.status_code, "http_error", str(exc.detail), None, exc.headers
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled API error on %s %s", request.method, request.url.path)
    return _error_response(
        500,
        "internal_error",
        "The request failed unexpectedly. Check server logs for diagnostic details.",
        {"exception_type": type(exc).__name__},
    )


def _engine_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, EngineUnavailableError):
        return _error_response(503, "engine_unavailable", str(exc))
    engine_exception = type(exc).__name__
    details = getattr(exc, "details", None)
    if engine_exception in {
        "SchemaError",
        "ValidationError",
        "SplitError",
        "ConfigurationError",
        "InsufficientHistoryError",
        "LeakageError",
    } or isinstance(exc, (ValueError, TypeError, KeyError)):
        return _error_response(
            422, "engine_input_error", str(exc), details
        )
    logger.exception("Engine operation failed", exc_info=exc)
    return _error_response(
        500,
        "engine_operation_failed",
        f"Engine operation failed with {engine_exception}.",
        details,
    )


def _input_provenance(payload: Any) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    counts = {
        key: len(value)
        for key, value in data.items()
        if isinstance(value, list)
    }
    return {
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "row_counts": counts,
        "synthetic": data.get("synthetic", False),
        "seed": data.get("seed"),
        "payload": data,
    }


def _record_failed_run(run_id: str, exc: Exception) -> None:
    finish_run(
        run_id,
        "failed",
        error={
            "exception_type": type(exc).__name__,
            "message": str(exc),
        },
    )


def _with_run_id(response: JSONResponse, run_id: str) -> JSONResponse:
    body = json.loads(response.body)
    error = body.get("error")
    if isinstance(error, dict):
        details = error.get("details")
        if isinstance(details, dict):
            details["run_id"] = run_id
        else:
            error["details"] = {"run_id": run_id, "details": details}
        response.body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
    response.headers["X-Run-ID"] = run_id
    return response


def _risk_for_run(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") or {}
    input_data = (record.get("input_provenance") or {}).get("payload", {})
    indicators: list[dict[str, Any]] = []
    unavailable: list[str] = []
    if record["operation"] == "backtest":
        for row in result.get("policy_metrics", []):
            for field in (
                "unmet_demand_rate",
                "stockout_day_rate",
                "expired_units",
                "freight_cost",
                "constraint_violations",
            ):
                indicators.append(
                    {
                        "name": field,
                        "kind": "observed_simulation_metric",
                        "policy": row.get("policy"),
                        "value": row.get(field),
                    }
                )
        unavailable.extend(
            [
                "expiry financial exposure: landed unit costs are not supplied",
                "lost-sales exposure: unit margin is not supplied",
                "holding-cost exposure: no holding-rate input is supplied",
                "capacity slack: the current engine contract does not return daily residual capacity",
            ]
        )
    else:
        forecast = result.get("forecast", result)
        forecasts = forecast.get("forecasts", []) if isinstance(forecast, dict) else []
        by_sku: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for row in forecasts:
            sku = str(row.get("sku_id", ""))
            for field in ("point_forecast", "lower_bound", "upper_bound"):
                value = row.get(field)
                if value is not None:
                    by_sku[sku][field] += float(value)
        for sku, totals in by_sku.items():
            indicators.append(
                {
                    "name": "forecast_uncertainty_interval",
                    "kind": "measured_forecast_interval",
                    "sku_id": sku,
                    "point_demand_units": totals.get("point_forecast"),
                    "lower_demand_units": totals.get("lower_bound"),
                    "upper_demand_units": totals.get("upper_bound"),
                    "interval_width_units": (
                        totals["upper_bound"] - totals["lower_bound"]
                        if "upper_bound" in totals and "lower_bound" in totals
                        else None
                    ),
                }
            )
        if record["operation"] == "plan":
            stock_by_sku: dict[str, float] = defaultdict(float)
            expiring_by_sku: dict[str, float] = defaultdict(float)
            horizon_end = date.fromisoformat(forecast["origin"]) + timedelta(
                days=int(forecast["horizon_days"])
            )
            for batch in input_data.get("inventory_batches", []):
                sku = str(batch["sku_id"])
                quantity = float(batch["quantity"])
                stock_by_sku[sku] += quantity
                expiry = batch.get("expiry_date")
                if expiry is not None and date.fromisoformat(str(expiry)[:10]) <= horizon_end:
                    expiring_by_sku[sku] += quantity
            for sku in sorted(set(stock_by_sku) | set(by_sku)):
                expected = by_sku[sku].get("point_forecast", 0.0)
                stock = stock_by_sku.get(sku, 0.0)
                indicators.append(
                    {
                        "name": "gross_network_stock_vs_forecast",
                        "kind": "observed_input_comparison_not_eligibility_adjusted",
                        "sku_id": sku,
                        "gross_network_stock_units": stock,
                        "point_forecast_units": expected,
                        "gross_shortage_units": max(0.0, expected - stock),
                        "expiring_within_horizon_units": expiring_by_sku.get(sku, 0.0),
                    }
                )
            capacity_rows = input_data.get("capacities", [])
            if capacity_rows and all(
                "sku_id" not in row and "warehouse_id" not in row
                for row in capacity_rows
            ):
                shipped_by_destination: dict[str, float] = defaultdict(float)
                for shipment in result.get("plan", []):
                    shipped_by_destination[str(shipment["destination_id"])] += float(
                        shipment["allocated_quantity"]
                    )
                for capacity in capacity_rows:
                    destination = str(capacity["destination_id"])
                    slack = float(capacity["capacity_units"]) - shipped_by_destination.get(
                        destination, 0.0
                    )
                    indicators.append(
                        {
                            "name": "planned_destination_capacity_slack",
                            "kind": "measured_plan_capacity_units_only",
                            "destination_id": destination,
                            "capacity_units": float(capacity["capacity_units"]),
                            "planned_shipment_units": shipped_by_destination.get(
                                destination, 0.0
                            ),
                            "remaining_capacity_units": slack,
                        }
                    )
            unavailable.extend(
                [
                    "realized unmet demand: no held-out daily simulation is part of the plan operation",
                    "expiry financial exposure: landed unit costs are not supplied",
                    "actual expiry wastage: gross expiry exposure does not model sell-through before expiry",
                    "destination on-hand stock: absent from the current planning input contract",
                ]
            )
        else:
            unavailable.append("inventory availability: forecast runs do not include inventory inputs")
    return {
        "run_id": record["run_id"],
        "operation": record["operation"],
        "synthetic": bool(input_data.get("synthetic", False)),
        "indicators": indicators,
        "unavailable_indicators": unavailable,
        "risk_score": None,
        "limitations": [
            "Indicators are observed quantities or forecast intervals; no weighted composite risk score is calculated.",
            "Synthetic-data status is inherited from the recorded request and must not be interpreted as real operational evidence.",
        ],
    }


def _csv_export(record: dict[str, Any]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=("run_id", "operation", "section", "row_index", "record_json"),
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerow(
        {
            "run_id": record["run_id"],
            "operation": record["operation"],
            "section": "run",
            "row_index": 0,
            "record_json": json.dumps(
                {
                    "created_at": record["created_at"],
                    "status": record["status"],
                    "input_provenance": {
                        key: value
                        for key, value in record["input_provenance"].items()
                        if key != "payload"
                    },
                    "configuration": record["configuration"],
                    "error": record["error"],
                },
                ensure_ascii=False,
                allow_nan=False,
            ),
        }
    )
    result = record.get("result") or {}
    for section, value in result.items():
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        else:
            rows = [{"value": value}]
        for index, row in enumerate(rows):
            writer.writerow(
                {
                    "run_id": record["run_id"],
                    "operation": record["operation"],
                    "section": section,
                    "row_index": index,
                    "record_json": json.dumps(
                        row, ensure_ascii=False, allow_nan=False
                    ),
                }
            )
    return output.getvalue().encode("utf-8")


@app.get("/api/health", response_model=HealthResponse)
def health() -> dict[str, Any]:
    ready, error = engine_readiness()
    return {
        "status": "running",
        "engine_ready": ready,
        "engine_error": error,
    }


@app.get("/api/demo-data")
def demo_data(
    seed: int = Query(default=42, ge=0, le=2**32 - 1),
    profile: Literal["compact", "prd"] = Query(
        default="prd", pattern="^(compact|prd)$"
    ),
) -> dict[str, Any]:
    """Return reproducible synthetic input rows at the documented PRD scale."""
    try:
        return generate_demo_data(seed=seed, profile=profile)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_demo_profile", "message": str(exc)},
        ) from exc


@app.post("/api/data/validate")
def validate_data(
    payload: DataValidateRequest,
    _user: AuthenticatedUser = Depends(require_verified_user),
) -> dict[str, Any]:
    try:
        return validate_dataset(
            payload, scope=payload.validation_scope
        ).model_dump(mode="json")
    except EngineUnavailableError as exc:
        return _engine_error(exc)


@app.post("/api/forecast", response_model=ForecastResponse)
def forecast(
    payload: ForecastRequest,
    user: AuthenticatedUser = Depends(require_verified_user),
) -> Any:
    provenance = _input_provenance(payload)
    run_id, created_at = create_run(
        "forecast",
        user.uid,
        provenance,
        {"horizon_days": payload.horizon_days, "origin": payload.origin},
    )
    try:
        result = run_forecast(
            payload.demand_history,
            origin=payload.origin,
            horizon_days=payload.horizon_days,
        )
        response = {**result.response, "run_id": run_id, "created_at": created_at}
        finish_run(run_id, "succeeded", result=response)
        return response
    except Exception as exc:
        _record_failed_run(run_id, exc)
        return _with_run_id(_engine_error(exc), run_id)


@app.post("/api/plan", response_model=PlanResponse)
def plan(
    payload: PlanRequest,
    user: AuthenticatedUser = Depends(require_verified_user),
) -> Any:
    provenance = _input_provenance(payload)
    run_id, created_at = create_run(
        "plan",
        user.uid,
        provenance,
        {
            "horizon_days": payload.horizon_days,
            "solver_time_limit_seconds": min(
                payload.solver_time_limit_seconds, settings.max_solver_seconds
            ),
        },
    )
    try:
        missing_tables = [
            table
            for table in (
                "inventory_batches",
                "lanes",
                "transport_costs",
            )
            if not getattr(payload, table)
        ]
        if missing_tables:
            error = {
                "code": "plan_input_incomplete",
                "message": (
                    "Allocation requires non-empty inventory_batches, lanes, "
                    "and transport_costs in addition to demand_history."
                ),
                "details": {"missing_tables": missing_tables},
            }
            finish_run(run_id, "failed", error=error)
            return _with_run_id(
                _error_response(
                    422,
                    error["code"],
                    error["message"],
                    error["details"],
                ),
                run_id,
            )
        result = run_plan(
            demand_history=payload.demand_history,
            inventory_batches=payload.inventory_batches,
            lanes=payload.lanes,
            transport_costs=payload.transport_costs,
            capacities=payload.capacities,
            sku_min_shelf_life_days=payload.sku_min_shelf_life_days,
            held_out_actuals=payload.held_out_actuals,
            origin=payload.origin or payload.as_of,
            horizon_days=payload.horizon_days,
            solver_time_limit_seconds=min(
                payload.solver_time_limit_seconds, settings.max_solver_seconds
            ),
        )
        response = {**result, "run_id": run_id, "created_at": created_at}
        plan_status = result.get("solver", {}).get("status")
        plan_verified = result.get("verification", {}).get("is_valid") is True
        record_status = (
            "succeeded"
            if plan_status in {"optimal", "feasible"} and plan_verified
            else "partial_failure"
        )
        finish_run(run_id, record_status, result=response)
        return response
    except Exception as exc:
        _record_failed_run(run_id, exc)
        return _with_run_id(_engine_error(exc), run_id)


@app.post("/api/backtest", response_model=BacktestResponse)
def backtest(
    payload: BacktestRequest,
    user: AuthenticatedUser = Depends(require_verified_user),
) -> Any:
    provenance = _input_provenance(payload)
    run_id, created_at = create_run(
        "backtest",
        user.uid,
        provenance,
        {
            "evaluation_days": payload.evaluation_days,
            "dispatch_horizon_days": 7,
            "solver_time_limit_seconds": min(
                payload.solver_time_limit_seconds, settings.max_solver_seconds
            ),
        },
    )
    try:
        validation = validate_dataset(payload)
        if not validation.valid:
            error = {
                "code": "dataset_validation_failed",
                "message": "The backtest dataset contains blocking validation errors.",
                "details": validation.model_dump(mode="json"),
            }
            finish_run(run_id, "failed", error=error)
            return _with_run_id(
                _error_response(
                    422, error["code"], error["message"], error["details"]
                ),
                run_id,
            )
        result = run_backtest(
            demand_history=payload.demand_history,
            inventory_batches=payload.inventory_batches,
            warehouse_receipts=payload.warehouse_receipts,
            lanes=payload.lanes,
            transport_costs=payload.transport_costs,
            capacities=payload.capacities,
            sku_min_shelf_life_days=payload.sku_min_shelf_life_days,
            evaluation_actuals=payload.evaluation_actuals,
            as_of=payload.as_of,
            evaluation_days=payload.evaluation_days,
            solver_time_limit_seconds=min(
                payload.solver_time_limit_seconds, settings.max_solver_seconds
            ),
            synthetic=payload.synthetic,
            seed=payload.seed,
        )
        response = {
            **result,
            "run_id": run_id,
            "created_at": created_at,
        }
        finish_run(run_id, result["status"], result=response)
        return response
    except Exception as exc:
        _record_failed_run(run_id, exc)
        return _with_run_id(_engine_error(exc), run_id)


@app.get("/api/runs/{run_id}", response_model=RunRecord)
def read_run(
    run_id: str,
    user: AuthenticatedUser = Depends(require_verified_user),
) -> Any:
    try:
        record = get_run(run_id, user.uid)
    except Exception as exc:
        logger.exception("Failed to load run record %s", run_id)
        return _error_response(
            500,
            "run_store_error",
            "The run record could not be read.",
            {"exception_type": type(exc).__name__},
        )
    if record is None:
        return _error_response(
            404, "run_not_found", f"No run exists with ID {run_id}."
        )
    return record


@app.get("/api/runs/{run_id}/export")
def export_run(
    run_id: str,
    format: str = Query(default="json"),
    user: AuthenticatedUser = Depends(require_verified_user),
) -> Response:
    if format not in {"json", "csv"}:
        return _error_response(
            422,
            "unsupported_export_format",
            "Export format must be either 'json' or 'csv'.",
            {"supported_formats": ["json", "csv"]},
        )
    try:
        record = get_run(run_id, user.uid)
    except Exception as exc:
        logger.exception("Failed to export run record %s", run_id)
        return _error_response(
            500,
            "run_store_error",
            "The run record could not be read for export.",
            {"exception_type": type(exc).__name__},
        )
    if record is None:
        return _error_response(
            404, "run_not_found", f"No run exists with ID {run_id}."
        )
    if format == "json":
        body = json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
        media_type = "application/json"
    else:
        body = _csv_export(record)
        media_type = "text/csv; charset=utf-8"
    if len(body) > settings.max_export_bytes:
        return _error_response(
            413,
            "export_too_large",
            f"Export exceeds the {settings.max_export_bytes}-byte limit.",
        )
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="optiqo-run-{run_id}.{format}"'
        },
    )


@app.get("/api/risk")
def risk(
    seed: int = Query(default=42, ge=0, le=2**32 - 1),
    run_id: str | None = None,
    user: AuthenticatedUser | None = Depends(optional_verified_user),
) -> Any:
    try:
        if run_id is not None:
            if user is None:
                raise HTTPException(
                    status_code=401,
                    detail={"code": "authentication_required", "message": "A Firebase ID token is required to inspect a run."},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            record = get_run(run_id, user.uid)
            if record is None:
                return _error_response(
                    404, "run_not_found", f"No run exists with ID {run_id}."
                )
            return _risk_for_run(record)
        return demo_supply_risks(seed=seed)
    except HTTPException:
        raise
    except Exception as exc:
        return _engine_error(exc)


@app.post("/api/risk/dataset")
def risk_for_dataset(
    payload: DatasetPayload,
    _user: AuthenticatedUser = Depends(require_verified_user),
) -> Any:
    try:
        if not payload.demand_history:
            return _error_response(
                422,
                "risk_input_incomplete",
                "Demand history is required to calculate forecast-based risk indicators.",
                {"missing_tables": ["demand_history"]},
            )
        report = validate_dataset(payload, scope="demand_only")
        if not report.valid:
            return _error_response(
                422,
                "risk_input_invalid",
                "Demand history contains blocking validation errors.",
                report.model_dump(mode="json"),
            )
        return dataset_supply_risks(payload)
    except Exception as exc:
        return _engine_error(exc)
