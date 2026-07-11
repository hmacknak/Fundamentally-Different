"""Structured runtime configuration.

All values come from environment variables — never hard-coded. For local
development, values may also be placed in a `.env` file (see
`config/example.env`); real deployments (CI, scheduled jobs) should set
environment variables directly through GitHub Actions / cloud secret
management instead, per docs/AUTOMATION_AND_DEPLOYMENT.md.

No secret value ever has a non-empty default here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def load_dotenv(path: str = ".env") -> None:
    """Populate os.environ from a simple KEY=VALUE file, if present.

    Existing environment variables are never overwritten. Not a full .env
    parser (no quoting/escaping) — sufficient for the flat key=value files
    this project uses.
    """
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip()


@dataclass(frozen=True)
class AppConfig:
    fmp_api_key: str | None
    fred_api_key: str | None
    database_url: str
    report_storage_path: str

    @classmethod
    def from_env(cls, env: dict | None = None) -> "AppConfig":
        e = env if env is not None else os.environ
        return cls(
            fmp_api_key=e.get("FMP_API_KEY") or None,
            fred_api_key=e.get("FRED_API_KEY") or None,
            database_url=e.get("DATABASE_URL") or "sqlite:///./amp.db",
            report_storage_path=e.get("REPORT_STORAGE_PATH", "output"),
        )
