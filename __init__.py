"""Optiqo AI/ML engine for demand forecasting and inventory allocation.

This directory is the package root (not a nested ``aiml/aiml`` tree).
"""

from .config import ColumnMap, EngineConfig, ForecastConfig, SplitConfig
from .exceptions import (
    ConfigurationError,
    InsufficientHistoryError,
    LeakageError,
    OptiqoAIMLError,
    SchemaError,
    SplitError,
    ValidationError,
)

__all__ = [
    "ColumnMap",
    "ConfigurationError",
    "EngineConfig",
    "ForecastConfig",
    "InsufficientHistoryError",
    "LeakageError",
    "OptiqoAIMLError",
    "SchemaError",
    "SplitConfig",
    "SplitError",
    "ValidationError",
]

__task__ = 1
__version__ = "0.1.0"
