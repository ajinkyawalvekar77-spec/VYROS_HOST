"""Domain exceptions for the Optiqo AI/ML engine.

Invalid inputs are rejected explicitly. Callers must not treat these as
recoverable “clean the value and continue” signals unless they re-validate.
"""

from __future__ import annotations

from typing import Any


class OptiqoAIMLError(Exception):
    """Base error for the AI/ML workstream."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ConfigurationError(OptiqoAIMLError):
    """Engine configuration is incomplete or internally inconsistent."""


class SchemaError(OptiqoAIMLError):
    """A frame is missing required columns or uses an unsupported layout."""


class ValidationError(OptiqoAIMLError):
    """A frame failed data-quality checks (types, ranges, duplicates, nulls)."""


class SplitError(OptiqoAIMLError):
    """Chronological split cutoffs are invalid or would leak across partitions."""


class InsufficientHistoryError(OptiqoAIMLError):
    """A series does not have enough past observations for the requested method."""


class LeakageError(OptiqoAIMLError):
    """A feature or split used information from the future of the prediction origin."""


class NotImplementedInTaskError(OptiqoAIMLError):
    """Requested behavior belongs to a later implementation task."""
