#!/usr/bin/env bash
# DISASTER-ONLY manual promotion. Never run while the original primary can write.
set -euo pipefail
umask 077
if [ "$#" -ne 2 ] || [ "$1" != "--primary-fenced" ] || [ "$2" != "--promote" ]; then
  echo "Usage: sudo aplus-standby-activate --primary-fenced --promote" >&2
  echo "PROHIBITED while original A+ primary can accept writes; confirm independent fencing first." >&2
  exit 2
fi
D=/opt/aplussolution-standby
cd "$D"
test -s "$D/recovery/aplussolution.env" && test -s "$D/failover-compose.yaml"
test -s "$D/recovery/app/backend/Dockerfile"
test -s "$D/recovery/app/frontend/Dockerfile"
test -s /opt/aplus-publisher/Caddyfile
test ! -e "$D/failover-active" || { echo 'Already promoted. Refusing second promotion.' >&2; exit 1; }
test "$(docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select pg_is_in_recovery()"' </dev/null | tr -d '[:space:]')" = t
# Refresh application source from the latest safely transferred package.
/usr/local/sbin/aplus-standby-prepare
# Extra guard: if the original STRATO primary still serves requests directly,
# do not trust a Cloudflare error as proof of a fenced origin.
ORIGIN_STATUS="$(curl -k -sS --connect-timeout 4 --max-time 9 -o /dev/null -w '%{http_code}' \
   --resolve 'app.aplus-solution.de:443:[2a01:239:44b:d900::1]' \
   https://app.aplus-solution.de/health/ 2>/dev/null || true)"
if [ "$ORIGIN_STATUS" = 200 ]; then
  echo 'ORIGINAL_PRIMARY_IS_STILL_RESPONDING: refusing promotion.' >&2
  exit 1
fi
echo "Original-primary direct HTTPS probe did not return 200."
echo "Operator asserted all production writers and original PostgreSQL were independently fenced."
# Preserve the last standby state before taking the one-way promotion action.
/usr/local/sbin/aplus-standby-snapshot-history
systemctl disable --now aplus-standby-file-sync.timer
systemctl stop aplus-standby-file-sync.service || true
systemctl disable --now aplus-standby-replication-tunnel.service
docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select pg_promote(wait_seconds => 60)"' </dev/null | grep -qx t
test "$(docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select pg_is_in_recovery()"' </dev/null | tr -d '[:space:]')" = f
# The old guarded standby compose must never be used again after promotion.
touch "$D/failover-active"
docker compose --env-file "$D/recovery/aplussolution.env" -f "$D/failover-compose.yaml" up -d db redis
BUILD=(docker compose --env-file "$D/recovery/aplussolution.env" -f "$D/failover-compose.yaml")
nice -n 10 ionice -c3 "${BUILD[@]}" build backend frontend
"${BUILD[@]}" run --rm --no-deps backend python manage.py collectstatic --noinput
"${BUILD[@]}" up -d backend frontend edge
BACKEND_ID="$("${BUILD[@]}" ps -q backend)"
test -n "$BACKEND_ID"
HEALTH=0
for i in $(seq 1 30); do
  if docker exec "$BACKEND_ID" curl -fsS --connect-timeout 2 --max-time 4 \
        -H 'Host: app.aplus-solution.de' http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
    HEALTH=1
    break
  fi
  sleep 3
done
test "$HEALTH" -eq 1 || { echo 'Backend not healthy; Publisher route remains untouched.' >&2; exit 1; }
cd /opt/aplus-publisher
CADDY_ID="$(docker compose ps -q caddy)"
test -n "$CADDY_ID"
docker network connect aplus_failover_net "$CADDY_ID" 2>/dev/null || \
  docker network inspect aplus_failover_net -f '{{range .Containers}}{{.Name}} {{end}}' | grep -F "$(docker inspect -f '{{.Name}}' "$CADDY_ID" | sed 's|^/||')" >/dev/null
# Verify Publisher's Caddy can resolve and query the *internal* A+ edge.
docker exec "$CADDY_ID" wget -q -O /dev/null --header 'Host: app.aplus-solution.de' http://edge:80/health/
test ! -e "$D/recovery/publisher-Caddyfile.pre-failover"
cp -p /opt/aplus-publisher/Caddyfile "$D/recovery/publisher-Caddyfile.pre-failover"
if grep -Eq '(^|[[:space:],])app\.aplus-solution\.de([[:space:],]|$)' /opt/aplus-publisher/Caddyfile; then
  echo 'Publisher already declares A+ domain; manual inspection required.' >&2
  exit 1
fi
cat >>/opt/aplus-publisher/Caddyfile <<'CADDY'
# A+ Solution DR ingress, injected by the explicit manual failover procedure.
app.aplus-solution.de, solution.smarbiz.sbs {
  encode zstd gzip
  reverse_proxy edge:80
  header {
    X-Aplus-Origin "strato-publisher-failover"
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
  }
}
CADDY
if ! docker exec "$CADDY_ID" caddy validate --config /etc/caddy/Caddyfile; then
  cp -p "$D/recovery/publisher-Caddyfile.pre-failover" /opt/aplus-publisher/Caddyfile
  echo 'Invalid Publisher Caddy config rolled back; A+ database remains promoted.' >&2
  exit 1
fi
docker exec "$CADDY_ID" caddy reload --config /etc/caddy/Caddyfile
docker compose exec -T web curl -fsS --max-time 10 http://127.0.0.1:8000/healthz/ </dev/null >/dev/null
echo FAILOVER_DATABASE_PROMOTED_AND_BACKEND_READY
echo PUBLISHER_AND_APLUS_INTERNAL_INGRESS_READY
echo 'ACTION REQUIRED: update Cloudflare A/AAAA origin to 82.165.187.14; check HTTPS, then start ONE worker+beat set.'
echo 'The A+ Celery workers intentionally remain OFF until DNS cutover is independently verified.'
