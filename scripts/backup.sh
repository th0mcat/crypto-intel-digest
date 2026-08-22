#!/usr/bin/env bash
# Nightly pg_dump, keeps 14 days locally. Ship the directory off-box
# (rclone to object storage, or Hetzner storage box) — a backup on the
# same machine as the database is a convenience, not a backup.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-intel}" "${POSTGRES_DB:-intel}" \
  | gzip > "backups/intel-${STAMP}.sql.gz"

find backups -name 'intel-*.sql.gz' -mtime +14 -delete
echo "backup written: backups/intel-${STAMP}.sql.gz"
