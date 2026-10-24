"""Pydantic request/response contracts for the Optiqo API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetPayload(APIModel):
    as_of: date | None = None
    synthetic: bool = False
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    demand_history: list[dict[str, Any]] = Field(default_factory=list)
    inventory_batches: list[dict[str, Any]] = Field(default_factory=list)
    lanes: list[dict[str, Any]] = Field(default_factory=list)
    transport_costs: list[dict[str, Any]] = Field(default_factory=list)
    capacities: list[dict[str, Any]] = Field(default_factory=list)
    sku_min_shelf_life_days: dict[str, int] = Field(default_factory=dict)
    warehouse_receipts: list[dict[str, Any]] = Field(default_factory=list)


class DataValidateRequest(DatasetPayload):
    validation_scope: Literal["demand_only", "full_network"] = "full_network"


class ForecastRequest(APIModel):
    demand_history: list[dict[str, Any]] = Field(min_length=1)
    origin: date | None = None
    horizon_days: int = Field(default=7, ge=1, le=28)
    synthetic: bool = False
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


class PlanRequest(DatasetPayload):
    demand_history: list[dict[str, Any]] = Field(min_length=1)
    origin: date | None = None
    horizon_days: int = Field(default=7, ge=1, le=28)
    solver_time_limit_seconds: int = Field(default=60, ge=1, le=60)
    held_out_actuals: list[dict[str, Any]] | None = None


class Finding(BaseModel):
    severity: Literal["error", "warning"] = "error"
    table: str
    row: int | None = None
    field: str | None = None
    rule: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TableValidation(BaseModel):
    valid: bool
    row_count: int


class ValidationReport(BaseModel):
    validation_scope: Literal["demand_only", "full_network"]
    valid: bool
    error_count: int
    warning_count: int
    tables: dict[str, TableValidation]
    findings: list[Finding]


class ForecastResponse(BaseModel):
    model_name: str
    fallback_used: bool
    fallback_reason: str | None
    origin: date
    horizon_days: int
    history_rows_used: int
    history_rows_after_origin_ignored: int
    validation_metrics: dict[str, float | None]
    model_validation_metrics: dict[str, dict[str, float | None]]
    forecasts: list[dict[str, Any]]
    run_id: str | None = None
    created_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str
    engine_ready: bool
    engine_error: str | None = None


class SolverResponse(BaseModel):
    status: str
    objective_value: float | None
    solver_status_code: int | None
    constraints_added: int
    diagnostics: dict[str, Any]


class VerificationResponse(BaseModel):
    is_valid: bool
    checks_passed: int
    checks_failed: int
    checks_not_run: list[str]
    violations: list[dict[str, Any]]
    summary: str


class BenchmarkResponse(BaseModel):
    optimizer_status: str
    metrics: list[dict[str, Any]]
    assumptions: list[str]


class PlanResponse(BaseModel):
    forecast: ForecastResponse
    solver: SolverResponse
    plan: list[dict[str, Any]]
    verification: VerificationResponse
    explanations: list[dict[str, Any]]
    benchmark: BenchmarkResponse | None
    objective_note: str
    run_id: str | None = None
    created_at: datetime | None = None


class BacktestRequest(DatasetPayload):
    evaluation_actuals: list[dict[str, Any]] = Field(min_length=1)
    evaluation_days: int = Field(default=56, ge=7, le=56, multiple_of=7)
    solver_time_limit_seconds: int = Field(default=60, ge=1, le=60)


class BacktestResponse(BaseModel):
    run_id: str
    created_at: datetime
    status: Literal["succeeded", "partial_failure"]
    synthetic: bool
    seed: int | None
    evaluation_days: int
    evaluation_start: date
    evaluation_end: date
    policies: list[str]
    policy_metrics: list[dict[str, Any]]
    forecast_metrics: dict[str, Any]
    gain_decomposition: dict[str, Any]
    cycles: list[dict[str, Any]]
    forecasts: list[dict[str, Any]]
    allocations: list[dict[str, Any]]
    daily: list[dict[str, Any]]
    daily_inventory: list[dict[str, Any]]
    daily_network: list[dict[str, Any]]
    assumptions: list[str]


class RunRecord(BaseModel):
    run_id: str
    operation: Literal["forecast", "plan", "backtest"]
    created_at: datetime
    status: Literal["running", "succeeded", "partial_failure", "failed"]
    input_provenance: dict[str, Any]
    configuration: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None


class RiskIndicator(BaseModel):
    sku_id: str
    indicator: str
    is_flagged: bool
    usable_network_stock_units: float
    forecast_horizon_demand_units: float
    supply_shortage_units: float
    network_days_of_cover: float | None


class RiskResponse(BaseModel):
    synthetic: bool
    seed: int
    indicator_scope: str
    risk_score: float | None
    severity: str | None
    indicators: list[RiskIndicator]
    unavailable_indicators: list[str]
    limitations: list[str]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody
