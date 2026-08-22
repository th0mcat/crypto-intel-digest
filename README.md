# intel-system

A self-hosted Telegram bot that polls RSS, Reddit and the NVD CVE API, deduplicates and scores what it finds with a hand-tuned heuristic, and pushes one daily digest to a single operator.

```
 RSS x11 ─┐
 Reddit x5├─► collectors ──► normalise ──► triage ──► Postgres 16
 NVD CVE ─┘  (cursor +      (content-      (4 weights,   (events: kept
              circuit        hash dedup,    threshold     AND killed)
              breaker)       title-hash     0.45)              │
                             novelty)                          ▼
                                                     digest ──► Telegram
                                                    (07:00 UTC, chunked
                                                     to 4096 chars)
```

Everything above runs. Nothing above has run unattended in production for a week, which was my own exit criterion — see [Status](#status).

## Why it exists

I wanted one place that watched the crypto and cryptography feeds I actually care about — exchange/protocol news on one side, CVEs and primitive breaks on the other — without me opening fifteen tabs a day. Aggregators either drown you or editorialise. The interesting engineering problem was never fetching; it was deciding what deserves a push notification, and being able to audit that decision afterwards. So killed items stay in the database with their scores and reasons attached, because a filter you can't inspect is a filter you can't tune.

## How it works

Three collectors implement one small interface: take a cursor, return items plus the next cursor. RSS uses feedparser against 11 sources (CoinDesk, The Block, Bitcoin Optech, Ethereum blog, SEC, FCA, NIST CSRC, Project Zero, Schneier, NCSC, arXiv); Reddit uses app-only OAuth across 5 subs; NVD uses the v2.0 API with a keyword pre-filter, because "vulnerability" matches nearly every CVE and the useful gate is named primitives and libraries. Each runs on its own supervised asyncio task with its own interval. Repeated failures multiply that interval by 2^failures up to 12x, so a dead source stops hammering the API and stops flooding the logs.

Normalisation does two hashes: content hash for exact dedup, title hash for a naive three-day novelty check. Triage is a weighted sum of four factors — materiality 0.35, reputation 0.25, novelty 0.20, specificity 0.20 — kept above 0.45. Those five constants are hand-picked, not learned. I picked them, ran `scripts/selftest.py`, and adjusted until the kills looked right on real items. That's the honest provenance.

The trade-off I took deliberately: no embeddings in stage 1. Exact title hashing misses paraphrased reposts, which is the known ceiling here, and pgvector is provisioned for the fix — but a cheap explainable score that I can read in a log line beat a similarity model I'd have to debug at 3am. Frontier-model triage was always meant to be stage 2, gated behind a stage-1 that already filters most of the volume.

Postgres holds everything; migrations are numbered SQL applied idempotently at startup. Redis is in the compose file and is **not used by any application code** — it's dead weight I provisioned for a queue I never built, and it should probably be deleted.

## Quickstart

Docker is required. The Dockerfile pins Python 3.12; running bare-metal on a newer host Python (3.14) breaks the asyncpg and pydantic-core wheel builds, so don't.

First get two things: a bot token from [@BotFather](https://t.me/BotFather) (`/newbot`), and your numeric Telegram user id from [@userinfobot](https://t.me/userinfobot). The bot ignores every id except that one.

```bash
git clone <this-repo> intel-system && cd intel-system
cp .env.example .env
```

Edit `.env` and set three values — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OPERATOR_ID`, `POSTGRES_PASSWORD`. Everything else has a working default; Reddit credentials are optional and RSS + NVD run without them.

```bash
docker compose up -d --build
docker compose logs -f bot
```

You should get "System online" on Telegram within a few seconds. Then message the bot `/status`, `/sources`, `/kills`, or `/digest` to build a brief immediately rather than waiting for `DIGEST_HOUR_UTC`.

Offline logic check — no network, no database, 12 assertions, passing as of this commit:

```bash
docker compose run --rm --no-deps -e PYTHONPATH=/home/app \
  -v "$PWD/scripts:/home/app/scripts:ro" bot python scripts/selftest.py
```

Integration test against live feeds and a real Postgres (start the stack first):

```bash
docker compose run --rm -e PYTHONPATH=/home/app \
  -v "$PWD/scripts:/home/app/scripts:ro" bot python scripts/itest.py
```

Sources live in `app/feeds.yaml` — edit and restart the bot. Nightly backups are `scripts/backup.sh` (pg_dump via compose, prunes past 14 days); wire it to cron yourself and ship the output off-box.

## Status

1,362 lines of Python, one author, never deployed in anger.

Working, and verified by a real self-test run (12/12 assertions):

- Entity extraction (CVE regex, cashtag regex, keyword matching), content-hash dedup, title-hash novelty, and the triage scoring formula.

Working, exercised against real public APIs but not under a long-running deploy:

- All three collectors with cursor/pagination handling, capped exponential backoff on failure, idempotent numbered migrations, digest formatting with HTML escaping and 4096-character chunking, structured JSON logging, operator-only access filter.

Partial or unverified:

- `scripts/itest.py` is a real integration test (fetch counts, dedup, migration version, digest query) but needs live Postgres and was not run during this audit.
- The 7-day unattended soak test this project sets for itself has not been completed by anyone.
- Redis is provisioned by compose and used by nothing.
- A `feedback` column exists in the schema; nothing writes to it.
- pgvector extension is created; no vector column is used.

Not built:

- Near-duplicate clustering by embedding, stage-2 frontier-model triage, entity resolution and an alias store. All deferred to phase 2/3 and marked as such in the code.
- WhatsApp notifier: the class exists and raises `NotImplementedError` in `__init__`. It is a stub.
- X/Twitter collector: deliberately absent. The API pricing doesn't sustain continuous monitoring inside my budget, and the collector interface is small enough to add one later if a measured recall gap justifies it.
- No web UI. The bot is the entire interface.

## Stack

| Choice | Why, over the obvious alternative |
| --- | --- |
| Postgres 16 + pgvector | One store for events, cursors and (eventually) embeddings. Over SQLite, because pgvector and concurrent collector writes both want a server. |
| asyncpg | Raw SQL and a connection pool. Over SQLAlchemy, because the schema is four tables and an ORM would be the largest dependency in the project. |
| aiogram 3.13 | Native asyncio, so the bot shares one event loop with the collector tasks. Over python-telegram-bot, which I'd have had to bridge. |
| feedparser | RSS/Atom parsing is a swamp of malformed XML. Not writing that. |
| structlog | JSON lines out of the box, so `docker compose logs` is greppable without a log stack. |
| pydantic-settings | Config validated at boot, so a missing token fails at startup rather than on the first send. |
| Docker Compose | Single-VPS deploy, three services. Over Kubernetes, obviously. |
| Redis 7 | No reason that survived contact with the code. Should be removed. |

## Licence

MIT.
