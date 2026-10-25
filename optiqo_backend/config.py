"""Centralized backend configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    engine_path: Path
    run_store_path: Path
    cors_origins: tuple[str, ...]
    max_request_bytes: int
    max_export_bytes: int
    max_solver_seconds: int
    firebase_project_id: str | None
    allow_local_development_access: bool


def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    default_engine_path = (
        project_root
        if (project_root / "__init__.py").is_file()
        else Path(r"C:\Users\ajink\OneDrive\Desktop\aiml")
    )
    configured_engine = Path(
        os.environ.get("OPTIQO_ENGINE_PATH", str(default_engine_path))
    ).expanduser()
    default_run_store = (
        Path("/tmp/optiqo/runs.sqlite3")
        if os.environ.get("VERCEL") == "1"
        else Path.home() / ".optiqo" / "runs.sqlite3"
    )
    configured_run_store = Path(
        os.environ.get("OPTIQO_RUN_STORE_PATH", str(default_run_store))
    ).expanduser()
    configured_origins = os.environ.get(
        "OPTIQO_CORS_ORIGINS",
        "https://optiquo.vercel.app,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:8501,http://127.0.0.1:8501",
    )
    origins = tuple(
        origin.strip() for origin in configured_origins.split(",") if origin.strip()
    )
    return Settings(
        engine_path=configured_engine.resolve(),
        run_store_path=configured_run_store.resolve(),
        cors_origins=origins,
        max_request_bytes=int(
            os.environ.get("OPTIQO_MAX_REQUEST_BYTES", 256 * 1024 * 1024)
        ),
        max_export_bytes=int(
            os.environ.get("OPTIQO_MAX_EXPORT_BYTES", 256 * 1024 * 1024)
        ),
        max_solver_seconds=int(os.environ.get("OPTIQO_MAX_SOLVER_SECONDS", 60)),
        firebase_project_id=os.environ.get("FIREBASE_PROJECT_ID") or None,
        allow_local_development_access=os.environ.get(
            "OPTIQO_ALLOW_LOCAL_DEVELOPMENT_ACCESS", ""
        ).lower() in {"1", "true", "yes"},
    )
