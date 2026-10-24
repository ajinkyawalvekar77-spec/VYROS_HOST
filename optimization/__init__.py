
"""Optiqo inventory allocation, verification, and explanation package."""

from .constraints import add_constraints
from .eligibility import eligible_shipments
from .objective import build_objective
from .optimizer import AllocationResult, optimize_allocation
from .checker import AllocationCheckResult, verify_allocation
from .explanations import explain_allocation

__all__ = [
    "add_constraints",
    "eligible_shipments",
    "build_objective",
    "AllocationResult",
    "optimize_allocation",
    "AllocationCheckResult",
    "verify_allocation",
    "explain_allocation",
]
