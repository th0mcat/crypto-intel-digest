from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_operator_id: int
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


settings = Settings()
