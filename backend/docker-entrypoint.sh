#!/bin/sh
set -e
echo "[entrypoint] running migrations..."
alembic upgrade head
if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[entrypoint] scheduling demo seed after server is up..."
  (
    sleep 6
    python scripts/seed.py || echo "[entrypoint] seed failed, continuing without demo data"
  ) &
fi
exec "$@"
