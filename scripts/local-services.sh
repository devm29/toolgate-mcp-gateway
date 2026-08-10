#!/usr/bin/env bash
# Runs Postgres and Redis from local binaries for development without Docker.
# Data lives in .data/ inside the repo so nothing leaks into system-wide state.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/.data"
PG_DATA="$DATA/postgres"
PG_PORT="${TOOLGATE_PG_PORT:-5501}"
REDIS_PORT="${TOOLGATE_REDIS_PORT:-6401}"

# Homebrew can leave a postgres binary linked against a removed ICU, so pick the first one that runs.
find_pg_bin() {
  if [ -n "${PG_BIN:-}" ]; then echo "$PG_BIN"; return; fi
  for dir in /opt/homebrew/opt/postgresql@17/bin /opt/homebrew/opt/postgresql@16/bin \
             /Applications/Postgres.app/Contents/Versions/latest/bin /usr/local/bin "$(dirname "$(command -v postgres 2>/dev/null || echo /nonexistent/x)")"; do
    if [ -x "$dir/postgres" ] && "$dir/postgres" -V >/dev/null 2>&1; then echo "$dir"; return; fi
  done
  echo "no working postgres binary found; set PG_BIN" >&2
  exit 1
}
PG_BIN="$(find_pg_bin)"
export PATH="$PG_BIN:$PATH"

start() {
  mkdir -p "$DATA"
  if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    initdb -D "$PG_DATA" -U toolgate --auth=trust >/dev/null
  fi
  if ! pg_ctl -D "$PG_DATA" status >/dev/null 2>&1; then
    pg_ctl -D "$PG_DATA" -o "-p $PG_PORT -k $DATA -c listen_addresses=127.0.0.1" -l "$DATA/postgres.log" -w start >/dev/null
  fi
  for db in toolgate toolgate_test; do
    psql -h 127.0.0.1 -p "$PG_PORT" -U toolgate -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
      || psql -h 127.0.0.1 -p "$PG_PORT" -U toolgate -d postgres -qc "CREATE DATABASE $db"
  done
  if ! redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    redis-server --port "$REDIS_PORT" --bind 127.0.0.1 --dir "$DATA" --save "" --appendonly no \
      --daemonize yes --pidfile "$DATA/redis.pid" --logfile "$DATA/redis.log"
  fi
  echo "postgres :$PG_PORT  redis :$REDIS_PORT"
}

stop() {
  pg_ctl -D "$PG_DATA" -m fast stop >/dev/null 2>&1 || true
  redis-cli -p "$REDIS_PORT" shutdown nosave >/dev/null 2>&1 || true
  echo "stopped"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  *) echo "usage: $0 [start|stop]" >&2; exit 1 ;;
esac
