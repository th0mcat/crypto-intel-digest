# intel-system — Phases 0–1

Always-on stack: Postgres (+pgvector) · Redis · Telegram bot with structured
JSON logging and an external dead-man's switch.

**Phase 1 adds:** three collectors (RSS, Reddit, NVD/CVE) covering both the
cryptocurrency and cryptography-proper tracks, a normaliser with exact-hash
dedup, naive Stage-1 triage that retains its kills for audit, and a P2 daily
brief pushed to Telegram. Done when the brief arrives unattended for 7 days.

## Prerequisites (one-time)

1. **Telegram bot**: message [@BotFather](https://t.me/BotFather), `/newbot`,
   copy the token.
2. **Your operator id**: message [@userinfobot](https://t.me/userinfobot),
   copy the numeric id. The bot ignores all other ids.
3. **Dead-man's switch** (recommended): create a free check at
   [healthchecks.io](https://healthchecks.io) with period 10 min / grace 5 min,
   copy the ping URL. Alerts fire from their infrastructure when the System
   goes quiet — a wedged VPS can't report itself dead.
4. **VPS**: Hetzner CPX21/CPX31, Ubuntu 24.04. Harden before anything else:
   ```bash
   adduser ops && usermod -aG sudo,docker ops   # after installing docker
   # SSH keys only: set PasswordAuthentication no in /etc/ssh/sshd_config
   ufw default deny incoming && ufw allow OpenSSH && ufw enable
   apt install -y fail2ban unattended-upgrades
   ```
   Install Docker via [get.docker.com](https://get.docker.com). Tailscale for
   admin access is worth the five minutes.

## Deploy

```bash
git clone <repo> && cd intel-system
cp .env.example .env   # fill in token, operator id, db password, ping URL
docker compose up -d --build
docker compose logs -f bot
```

You should receive "System online" on Telegram within a few seconds.

## Verify Phase 0 exit criteria

- [ ] `/start` and `/status` answer on Telegram; `/status` shows postgres ok.
- [ ] `docker compose logs bot` shows JSON lines including `heartbeat_ping`.
- [ ] healthchecks.io shows the check up; `docker compose stop db` flips it
      to down within ~15 min (then `start` it again).
- [ ] `sudo reboot` — the stack comes back and the bot re-announces itself
      with no manual action.

## Backups

```bash
crontab -e   # as the ops user
15 3 * * * cd /home/ops/intel-system && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Then ship `backups/` off-box (rclone to any object storage). Local-only
backups die with the disk.

## Phase 1: sources, triage, and the daily brief

### Configuring sources

Everything is in [app/feeds.yaml](app/feeds.yaml) — edit and restart the bot.
- **rss / reddit**: `name`, `url` (rss only), `reputation` (0–1 trust prior).
- **keywords**: drive materiality scoring and entity tagging for RSS/Reddit.
- **nvd_keywords**: a *separate* gate for CVEs. Generic words like
  "vulnerability" match nearly every CVE, so NVD is scoped to named primitives
  and libraries (OpenSSL, TLS, RSA, post-quantum…). Prune this to your stack.

Reddit needs `REDDIT_CLIENT_ID`/`SECRET` (a free "script" app); leave them
blank and RSS + NVD still run. X/Twitter is deliberately absent — its API
can't sustain continuous monitoring within budget, and the swappable collector
design means it can be added later if a measured recall gap points at it.

### How triage works (Phase 1, naive)

Each item scores 0–1 on four weighted factors — materiality (keyword/entity
hits), source reputation, novelty (naive: unseen title in 3 days), and
specificity — and is **kept** if it clears `TRIAGE_KEEP_THRESHOLD` (default
0.45). Killed items are *retained* in the `events` table (`triage_kept=false`)
so you can audit what the filter discards. Phase 2 replaces novelty with
embeddings and adds the expensive Stage-2 frontier scorer.

### Bot commands

- `/status` — version, uptime, Postgres, schema, dead-man switch.
- `/sources` — per-collector health (last run, status, failure count).
- `/kills` — kept vs killed counts over 24h, and the kill rate.
- `/digest` — build and send the daily brief right now.

### Verify Phase 1 exit criteria

- [ ] `/sources` shows RSS + NVD (+ Reddit if configured) running with
      `✅` and recent timestamps.
- [ ] `/digest` produces a brief with real, clickable items.
- [ ] The brief arrives on its own each day at `DIGEST_HOUR_UTC` for 7 days.
- [ ] `/kills` shows a non-trivial kill rate (triage is actually filtering).

### Offline / integration tests

```bash
# Pure logic (no network, no db):
docker run --rm -e PYTHONPATH=/home/app -e TELEGRAM_BOT_TOKEN=x \
  -e TELEGRAM_OPERATOR_ID=1 -e DATABASE_URL=postgresql://x@x/x \
  -v "$PWD/scripts:/home/app/scripts:ro" intel-system-bot python scripts/selftest.py

# Live feeds + real Postgres (start db first via compose):
docker compose run --rm --no-deps -e PYTHONPATH=/home/app \
  -v "$PWD/scripts:/home/app/scripts:ro" bot python scripts/itest.py
```

## Layout

```
app/               bot, config, db pool, heartbeat, logging
app/collectors/    rss, reddit, nvd + base (circuit breaker in scheduler)
app/migrations/    numbered SQL, applied idempotently at startup
app/feeds.yaml     source + keyword config (edit this)
app/{normalise,triage,notifier,scheduler,digest,store}.py
db/init/           first-boot bootstrap (fresh volumes only)
scripts/           backup.sh, selftest.py, itest.py
docker-compose.yml
```

Next (Phase 2): two-stage triage with embeddings, near-duplicate clustering,
and one-tap useful/noise feedback buttons on every alert.
