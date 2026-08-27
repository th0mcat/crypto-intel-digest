from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Explicit channel selection. Set MODE=telegram or MODE=matrix in .env.
    # This takes precedence over any presence-based inference.
    mode: Literal["telegram", "matrix"] = "telegram"

    # Telegram credentials — leave blank when running in Matrix mode.
    telegram_bot_token: str = ""
    telegram_operator_id: int | None = None
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    healthcheck_url: str = ""
    heartbeat_interval_seconds: int = 300

    # Reddit collector (disabled if either is blank). Create a "script" app
    # at https://www.reddit.com/prefs/apps — app-only OAuth needs no password.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "intel-system/0.2 (by operator)"

    # NVD works without a key at 5 req/30s; a free key raises it to 50/30s.
    # https://nvd.nist.gov/developers/request-an-api-key
    nvd_api_key: str = ""

    # Matrix integration (all four fields must be set to enable Matrix).
    # Bot account: create a Matrix user on your homeserver and generate an
    # access token (Element → Settings → Help & About → Access Token).
    matrix_homeserver_url: str = ""
    matrix_user_id: str = ""          # e.g. @bot:example.org
    matrix_access_token: str = ""
    matrix_room_id: str = ""          # e.g. !abc123:example.org
    # Optional fallback if no access token is available (token preferred).
    matrix_password: str = ""
    # Only this Matrix user id may issue commands; everyone else is ignored.
    matrix_operator_user_id: str = ""

    # Daily P2 digest send time, UTC hour (0-23).
    digest_hour_utc: int = 7

    # Triage keep threshold (0-1). Survivors reach the digest; the rest are
    # retained as killed rows so the filter stays auditable.
    triage_keep_threshold: float = 0.45

    # Collector base intervals (seconds). Circuit breaker multiplies these on
    # repeated failure.
    rss_interval_seconds: int = 600
    reddit_interval_seconds: int = 300
    nvd_interval_seconds: int = 1800

    @field_validator("telegram_operator_id", mode="before")
    @classmethod
    def _blank_operator_id_to_none(cls, v):
        """Treat an unset/blank TELEGRAM_OPERATOR_ID as None instead of
        letting pydantic try (and fail) to parse "" as an int."""
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


settings = Settings()


def channel_mode() -> Literal["telegram", "matrix"]:
    """Return the active channel mode based on the explicit `mode` setting.

    The operator selects the channel explicitly via MODE=telegram|matrix in
    .env. This function validates that the required credentials for the
    selected mode are present and raises a clear error otherwise.
    """
    s = settings

    if s.mode == "telegram":
        if s.telegram_bot_token and s.telegram_operator_id is not None:
            return "telegram"
        raise RuntimeError(
            "MODE=telegram but TELEGRAM_BOT_TOKEN and/or TELEGRAM_OPERATOR_ID "
            "are not set. Configure both in .env, or set MODE=matrix instead."
        )

    if s.mode == "matrix":
        matrix_ok = bool(
            s.matrix_homeserver_url
            and s.matrix_user_id
            and s.matrix_room_id
            and (s.matrix_access_token or s.matrix_password)
        )
        if matrix_ok:
            return "matrix"
        raise RuntimeError(
            "MODE=matrix but required Matrix credentials are missing. Set "
            "MATRIX_HOMESERVER_URL + MATRIX_USER_ID + MATRIX_ROOM_ID + "
            "MATRIX_ACCESS_TOKEN (or MATRIX_PASSWORD) in .env."
        )

    raise RuntimeError(f"Unknown MODE '{s.mode}'. Use 'telegram' or 'matrix'.")
