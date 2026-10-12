#!/usr/bin/env bash
# Starts exactly one Celery worker and scheduler only after public DNS cutover.
set -euo pipefail
if [ "$#" -ne 1 ] || [ "$1" != "--dns-cutover-verified" ]; then
  echo "Usage: sudo aplus-standby-start-workers --dns-cutover-verified" >&2
  exit 2
fi
D=/opt/aplussolution-standby
test -f "$D/failover-active"
test -s "$D/recovery/aplussolution.env"
cd "$D"
test "$(docker compose --env-file "$D/recovery/aplussolution.env" -f "$D/failover-compose.yaml" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select pg_is_in_recovery()"' </dev/null | tr -d '[:space:]')" = f
H="$(mktemp)"
trap 'rm -f "$H"' EXIT
curl -fsS --max-time 20 -D "$H" -o /dev/null https://app.aplus-solution.de/health/
grep -Eiq '^x-aplus-origin:[[:space:]]*strato-publisher-failover' "$H" || {
  echo 'Public production origin is not the failover. Workers remain stopped.' >&2
  exit 1
}
docker compose --env-file "$D/recovery/aplussolution.env" -f "$D/failover-compose.yaml" --profile workers up -d celery celery-beat
echo SINGLE_FAILOVER_WORKER_AND_BEAT_STARTED
