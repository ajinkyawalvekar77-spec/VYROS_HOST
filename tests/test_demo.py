"""Tests for the reproducible engine demo entry point."""

from aiml.demo import run_synthetic_demo


def test_synthetic_demo_runs_the_real_engine_workflow() -> None:
    result = run_synthetic_demo()

    assert result.training.model_name in {
        "lightgbm",
        "seasonal_naive",
        "moving_average",
    }
    assert len(result.forecast) == 7
    assert result.allocation.status == "optimal"
    assert result.verification.is_valid
    assert len(result.benchmark.metrics) == 3
    assert set(result.benchmark.metrics["policy"]) == {
        "optiqo",
        "cheapest_first",
        "fefo_first",
    }
