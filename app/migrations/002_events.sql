-- Phase 1: raw archive, normalised events, collector cursors.
-- Killed events are retained (triage_kept = false) so the filter is auditable.

CREATE TABLE IF NOT EXISTS raw_events (
    id          bigserial PRIMARY KEY,
    source_type text NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    raw_hash    text NOT NULL,
    payload     jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_events_hash_idx ON raw_events (raw_hash);
CREATE INDEX IF NOT EXISTS raw_events_fetched_idx ON raw_events (fetched_at);

CREATE TABLE IF NOT EXISTS events (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source            text NOT NULL,          -- e.g. "rss:coindesk", "reddit:crypto"
    source_type       text NOT NULL,          -- rss | reddit | nvd
    author            text,
    url               text,
    title             text NOT NULL,
    raw_text          text NOT NULL DEFAULT '',
    published_at      timestamptz,
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    entities          jsonb NOT NULL DEFAULT '[]',
    source_reputation real NOT NULL DEFAULT 0.5,
    raw_hash          text NOT NULL UNIQUE,    -- exact-dedup key
    title_hash        text NOT NULL,           -- naive novelty key (Phase 2: embeddings)
    triage_score      real NOT NULL DEFAULT 0,
    triage_kept       boolean NOT NULL DEFAULT false,
    triage_reasons    jsonb NOT NULL DEFAULT '[]',
    digested          boolean NOT NULL DEFAULT false,
    feedback          text                     -- Phase 2: useful/noise buttons
);
CREATE INDEX IF NOT EXISTS events_kept_digest_idx
    ON events (triage_kept, digested, triage_score DESC);
CREATE INDEX IF NOT EXISTS events_published_idx ON events (published_at DESC);
CREATE INDEX IF NOT EXISTS events_title_hash_idx ON events (title_hash);
CREATE INDEX IF NOT EXISTS events_ingested_idx ON events (ingested_at DESC);

CREATE TABLE IF NOT EXISTS collector_state (
    source               text PRIMARY KEY,
    cursor               jsonb NOT NULL DEFAULT '{}',
    last_run_at          timestamptz,
    last_status          text,
    consecutive_failures integer NOT NULL DEFAULT 0
);
