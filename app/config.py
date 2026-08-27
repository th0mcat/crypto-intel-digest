"""Runtime settings shim for the maubot plugin.

All values are populated by :class:`app.plugin.CryptoIntelPlugin` during
``start()`` from the maubot config (``base-config.yaml``).  The rest of the
``app`` package imports ``from app.config import settings`` and reads plain
attributes — no environment variables, no pydantic, no .env file.
"""
from __future__ import annotations


class Settings:
    """Mutable bag of configuration values.  Set by the plugin before any
    background task or command handler accesses them.
    """

    # Database
    database_url: str = ""

    # Matrix room & access control
    matrix_room_id: str = ""
    matrix_operator_user_id: str = ""

    # Digest schedule
    digest_hour_utc: int = 7

    # Triage
    triage_keep_threshold: float = 0.45

    # Collector intervals (seconds)
    rss_interval_seconds: int = 600
    reddit_interval_seconds: int = 300
    nvd_interval_seconds: int = 1800

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "intel-system/0.3 (by operator)"

    # NVD
    nvd_api_key: str = ""

    # Healthcheck
    healthcheck_url: str = ""
    heartbeat_interval_seconds: int = 300


#: Module-level singleton populated by the plugin at startup.
settings = Settings()
