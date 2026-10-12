#!/usr/bin/env bash
# Non-destructive drill: restore a dated snapshot to a network-isolated ephemeral DB.
set -euo pipefail
umask 077
exec 9>/run/aplus-standby-restore-test.lock
flock -n 9 || { echo "Restore drill already running"; exit 1; }
D=/opt/aplussolution-standby
LATEST="$(find "$D/snapshots" -mindepth 1 -maxdepth 1 -type d -name 'backup-20*' | sort | tail -1)"
test -n "$LATEST" && test -s "$LATEST/database.dump"
(cd "$LATEST" && sha256sum --check --status SHA256SUMS)
NAME="aplus-restore-drill-$$"
finish() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap finish EXIT
docker run -d --name "$NAME" --network none --memory 384m --cpus 0.4 \
  -e POSTGRES_PASSWORD=local-drill-only -e POSTGRES_DB=aplussolution \
  postgres:16-alpine >/dev/null
READY=0
for i in $(seq 1 60); do
    if docker exec "$NAME" pg_isready -U postgres -d aplussolution >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 2
done
test "$READY" = 1 || { docker logs --tail 15 "$NAME" >&2; exit 1; }
docker exec -i "$NAME" pg_restore -U postgres -d aplussolution --no-owner --no-acl --exit-on-error < "$LATEST/database.dump"
COUNT="$(docker exec "$NAME" psql -U postgres -d aplussolution -Atqc "select count(*) from information_schema.tables where table_schema = 'public'" | tr -d '[:space:]')"
test "$COUNT" -gt 0
echo "ISOLATED_DATABASE_RESTORE_PASSED"
echo "RESTORED_PUBLIC_TABLES_COUNT $COUNT"
echo "RESTORE_SOURCE $(basename "$LATEST")"
echo "No production database, network or Publisher service was changed."
