# crypto-intel-digest

A [maubot](https://github.com/maubot/maubot) plugin that polls RSS, Reddit and
the NVD CVE API, deduplicates and scores what it finds with a hand-tuned
heuristic, and delivers one daily digest to a Matrix room.

```
 RSS x11 ─┐
 Reddit x5├─► collectors ──► normalise ──► triage ──► Postgres 16
 NVD CVE ─┘  (cursor +      (content-      (4 weights,   (events: kept
              circuit        hash dedup,    threshold     AND killed)
              breaker)       title-hash     0.45)              │
                            novelty)                          ▼
                                                    digest ──► Matrix room
                                                   (07:00 UTC)  (via maubot)
```

## Why it exists

I wanted one place that watched the crypto and cryptography feeds I actually
care about — exchange/protocol news on one side, CVEs and primitive breaks on
the other — without opening fifteen tabs a day.  The interesting engineering
problem was never fetching; it was deciding what deserves a push notification,
and being able to audit that decision afterwards.  Killed items stay in the
database with their scores and reasons attached, because a filter you can't
inspect is a filter you can't tune.

## How it works

Three collectors implement one small interface: take a cursor, return items plus
the next cursor.  RSS uses feedparser against 11 sources; Reddit uses app-only
OAuth across 5 subs; NVD uses the v2.0 API with a keyword pre-filter (because
"vulnerability" matches nearly every CVE and the useful gate is named primitives
and libraries).  Each runs on its own supervised asyncio task inside the maubot
server process.  Repeated failures multiply the polling interval by 2^failures
up to 12×, so a dead source stops hammering the API without silently dropping it.

Normalisation does two hashes: content hash for exact dedup, title hash for a
naive three-day novelty check.  Triage is a weighted sum of four factors —
materiality 0.35, reputation 0.25, novelty 0.20, specificity 0.20 — kept above
0.45.  Those constants are hand-picked, not learned, and every killed item keeps
its score and reasons in the database.

Postgres holds everything; migrations are numbered SQL applied idempotently at
plugin startup.

## Prerequisites

* A running **maubot** instance (v0.4.0 or later recommended).
  See https://github.com/maubot/maubot for installation instructions.
* **PostgreSQL 14+** (with the `pgvector` extension available).
* The `mbc` command-line tool from the maubot project (for building the
  `.mbp` plugin package):
  ```bash
  pip install maubot
  ```

## Building and installing the plugin

```bash
# 1. Build the plugin package
mbc build

# This produces:  org.example.crypto-intel-digest-0.3.0.mbp
```

Upload the `.mbp` file through the maubot management UI
(`https://<your-maubot-instance>/_matrix/maubot/`) or via the REST API:

```bash
mbc upload org.example.crypto-intel-digest-0.3.0.mbp \
    --server https://<your-maubot-instance>/_matrix/maubot/
```

Then create a **bot instance** in the maubot UI, select the plugin, and
configure it (see [Configuration](#configuration) below).

## Configuration

All settings live in `base-config.yaml` and are edited through the maubot
management UI — no `.env` file or environment variables required.

| Key | Default | Description |
|-----|---------|-------------|
| `database_url` | *(required)* | PostgreSQL connection string, e.g. `******localhost:5432/intel` |
| `room_id` | *(required)* | Matrix room to post digests to and receive commands from, e.g. `!abc123:example.org` |
| `operator_user_id` | *(required)* | Only this Matrix user may issue commands; everyone else is silently ignored, e.g. `@you:example.org` |
| `digest_hour_utc` | `7` | UTC hour (0–23) at which the daily digest is sent |
| `triage_keep_threshold` | `0.45` | Score threshold (0–1); items at or above this value appear in the digest |
| `rss_interval_seconds` | `600` | Polling interval for RSS feeds |
| `reddit_interval_seconds` | `300` | Polling interval for Reddit |
| `nvd_interval_seconds` | `1800` | Polling interval for NVD |
| `reddit_client_id` | `""` | Reddit "script" app client id (leave blank to disable Reddit) |
| `reddit_client_secret` | `""` | Reddit "script" app client secret |
| `reddit_user_agent` | `"intel-system/0.3 (by operator)"` | Reddit API user agent string |
| `nvd_api_key` | `""` | NVD API key (optional; raises rate limit from 5 to 50 req/30 s) |
| `healthcheck_url` | `""` | healthchecks.io (or compatible) ping URL for the dead-man's switch |
| `heartbeat_interval_seconds` | `300` | How often to ping `healthcheck_url` |

## Available commands

All commands use a **bang prefix** and may only be issued by the configured
`operator_user_id` in the configured `room_id`.

| Command | Description |
|---------|-------------|
| `!help` / `!start` | List available commands |
| `!status` | Database reachability, schema version, uptime |
| `!sources` | Per-collector health (last run time, consecutive failures) |
| `!kills` | Triage keep/kill counts for the last 24 h |
| `!digest` | Trigger the daily digest immediately |

## Database setup

The plugin applies its own migrations on startup (idempotent numbered SQL
files in `app/migrations/`).  You only need to create the database and user
beforehand:

```sql
CREATE DATABASE intel;
CREATE USER intel WITH PASSWORD 'change-me';
GRANT ALL PRIVILEGES ON DATABASE intel TO intel;
```

For local development with Docker Compose, the provided `docker-compose.yml`
starts a PostgreSQL instance with the correct user/database.  Update the
`POSTGRES_PASSWORD` in `.env` (copy from `.env.example`) and run:

```bash
docker compose up -d postgres
```

Then set `database_url` in the maubot plugin config to:
```
******localhost:5432/intel
```

## Source configuration

Feed sources live in `app/feeds.yaml`.  Edit them and rebuild + re-upload the
plugin to apply changes.  Per-source reputation scores (0–1) affect triage
weighting; adjust them based on observed signal quality.

## Self-test (offline logic check)

```bash
PYTHONPATH=. python scripts/selftest.py
```

This runs 12 assertions against the triage scoring and normalisation logic
without requiring a database or network.

## Integration test (requires live Postgres)

```bash
PYTHONPATH=. python scripts/itest.py
```

Exercises the full pipeline against live feeds and a real Postgres instance.
Set `DATABASE_URL` in the environment or ensure `base-config.yaml` is
populated before running.

## Status

Working business logic (verified by self-test):

* Entity extraction (CVE regex, cashtag regex, keyword matching), content-hash
  dedup, title-hash novelty, and the triage scoring formula.

Working, exercised against real public APIs:

* All three collectors with cursor/pagination, capped exponential backoff,
  idempotent numbered migrations, digest formatting, structured JSON logging,
  operator-only access filter.

Not built (deferred to later phases):

* Near-duplicate clustering by embedding (pgvector is provisioned).
* Stage-2 frontier-model triage.
* Entity resolution and alias store.
* X/Twitter collector (API pricing doesn't sustain continuous monitoring).

## Stack

| Choice | Why |
|--------|-----|
| maubot | Mature, actively maintained Matrix bot framework; handles Matrix sync, event dispatch and plugin lifecycle so this code doesn't have to. |
| Postgres 16 + pgvector | One store for events, cursors and (eventually) embeddings. |
| asyncpg | Raw SQL and a connection pool — no ORM for four tables. |
| feedparser | RSS/Atom parsing is a swamp of malformed XML. |
| structlog | JSON lines out of the box, so logs are greppable without a log stack. |
| aiohttp | Async HTTP for Reddit and NVD collectors. |

## Licence

MIT.
