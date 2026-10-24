"""Command-line entry point for the Optiqo package demo."""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Optiqo engine demo or launch its local desktop UI."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--demo",
        action="store_true",
        help="run the full workflow using deterministic synthetic data",
    )
    mode.add_argument(
        "--ui",
        action="store_true",
        help="launch the local CSV-input desktop UI",
    )
    args = parser.parse_args(argv)

    if args.ui:
        from .demo_ui import launch

        launch()
        return 0

    from .demo import run_synthetic_demo

    result = run_synthetic_demo()
    output = {
        "data_notice": "Deterministic synthetic data; not production data.",
        "selected_model": result.training.model_name,
        "fallback_reason": result.training.fallback_reason,
        "forecast_rows": len(result.forecast),
        "forecast_horizon_days": int(result.forecast["horizon_day"].nunique()),
        "forecast_validation_metrics": result.training.validation_metrics,
        "solver_status": result.allocation.status,
        "allocation_units": float(result.allocation.plan["allocated_quantity"].sum()),
        "verification_is_valid": result.verification.is_valid,
        "verification_checks_failed": result.verification.checks_failed,
        "benchmark_metrics": result.benchmark.metrics.to_dict(orient="records"),
    }
    print(json.dumps(output, indent=2, default=str))
    return (
        0
        if result.verification.is_valid
        and result.allocation.status in {"optimal", "feasible"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
