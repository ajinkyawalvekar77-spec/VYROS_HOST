"""Put the parent of this workspace on sys.path so ``import aiml`` works.

The workspace folder itself is the ``aiml`` package (no nested aiml/aiml).
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PARENT = WORKSPACE_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from aiml.config import EngineConfig  # noqa: E402


@pytest.fixture
def engine_config() -> EngineConfig:
    return EngineConfig()


@pytest.fixture
def daily_demand() -> pd.DataFrame:
    """Deterministic 40-day panel with a zero-demand day. Not production data."""
    start = date(2024, 1, 1)
    rows: list[dict[str, object]] = []
    for sku, dest, offset in (("sku-a", "dest-1", 0), ("sku-b", "dest-1", 3)):
        for i in range(40):
            day = start + timedelta(days=i)
            quantity = 0.0 if i == 10 else float(i + 1 + offset)
            rows.append(
                {
                    "sku_id": sku,
                    "destination_id": dest,
                    "demand_date": day,
                    "quantity": quantity,
                }
            )
    return pd.DataFrame(rows)
