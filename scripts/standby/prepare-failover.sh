#!/usr/bin/env bash
# Safe, repeatable PREPARATION ONLY. Never promote PostgreSQL or start app writers.
set -euo pipefail
umask 077
D=/opt/aplussolution-standby
test -s "$D/compose.yaml"
test -s "$D/recovery/aplussolution.env"
test -s "$D/recovery/app-source.tgz"
test -d "$D/media"
test -s /opt/aplus-publisher/Caddyfile
cd "$D"
STATE="$(docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select pg_is_in_recovery()"' </dev/null | tr -d '[:space:]')"
test "$STATE" = t || { echo 'Not a read-only standby. Aborting preparation.' >&2; exit 1; }
docker network inspect aplus_standby_net >/dev/null
docker network inspect aplus_failover_net >/dev/null 2>&1 || docker network create --driver bridge aplus_failover_net >/dev/null
TMP="$(mktemp -d "$D/recovery/.app-staged.XXXXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT
ionice -c3 nice -n 10 tar -xzf "$D/recovery/app-source.tgz" -C "$TMP"
test -s "$TMP/backend/Dockerfile"
test -s "$TMP/backend/config/settings.py"
test -s "$TMP/frontend/Dockerfile"
test -s "$TMP/frontend/package.json"
test -s "$TMP/Caddyfile"
if [ -d "$D/recovery/app" ]; then
  rm -rf "$D/recovery/app.previous"
  mv "$D/recovery/app" "$D/recovery/app.previous"
fi
mv "$TMP" "$D/recovery/app"
trap - EXIT
test -s "$D/failover-compose.yaml" && test -s "$D/failover-edge.Caddyfile"
chmod -R go-rwx "$D/recovery"
docker compose --env-file "$D/recovery/aplussolution.env" -f "$D/failover-compose.yaml" config --quiet
# Only standby DB may be running. No frontend, backend, Celery or Caddy yet.
test "$(docker ps --format '{{.Names}}' | grep -c '^aplussolution-standby-' || true)" -eq 1
cd /opt/aplus-publisher
docker compose exec -T web curl -fsS --max-time 10 http://127.0.0.1:8000/healthz/ </dev/null >/dev/null
echo FAILOVER_SOURCE_STAGED_AND_VALIDATED
echo EMERGENCY_COMPOSE_VALID
echo ALL_APP_WORKERS_REMAIN_STOPPED
echo PUBLISHER_UNAFFECTED
