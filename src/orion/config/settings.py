"""Configuration loading.

Config is a TOML file validated by a strict Pydantic model: unknown keys and
wrong types are errors, so a typo cannot silently disable a safety setting.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CONFIG_NAME = "orion.toml"


class OrionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path = Path("data")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Dry-run is the default: a fresh install plans actions but executes none.
    dry_run_default: bool = True
    kill_hotkey: str = "ctrl+alt+end"
    simulated_steps: int = Field(default=10, ge=1, le=100)
    simulated_step_seconds: float = Field(default=1.0, gt=0, le=30)

    @field_validator("kill_hotkey")
    @classmethod
    def _hotkey_has_key(cls, v: str) -> str:
        parts = [p.strip().lower() for p in v.split("+") if p.strip()]
        if not parts:
            raise ValueError("kill_hotkey must not be empty")
        return "+".join(parts)

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "orion.db"


def load_config(path: Path | None = None) -> OrionConfig:
    """Load config from `path`, or `./orion.toml` if present, else defaults.

    An explicitly given path that does not exist is an error.
    """
    if path is None:
        candidate = Path(DEFAULT_CONFIG_NAME)
        if not candidate.exists():
            return OrionConfig()
        path = candidate
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return OrionConfig(**raw.get("orion", {}))
