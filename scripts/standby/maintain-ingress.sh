#!/usr/bin/env bash
# No action until explicit disaster promotion marker exists.
set -euo pipefail
D=/opt/aplussolution-standby
test -f "$D/failover-active" || exit 0
test -s /opt/aplus-publisher/Caddyfile
cd /opt/aplus-publisher
CADDY_ID="$(docker compose ps -q caddy)"
test -n "$CADDY_ID"
if ! docker network inspect aplus_failover_net -f '{{range .Containers}}{{.Name}} {{end}}' | grep -F "$(docker inspect -f '{{.Name}}' "$CADDY_ID" | sed 's|^/||')" >/dev/null; then
  docker network connect aplus_failover_net "$CADDY_ID"
fi
if ! grep -Fq '# A+ Solution DR ingress, injected' Caddyfile; then
  # Never silently alter an unexpected conflicting Caddy site declaration.
  if grep -Eq '(^|[[:space:],])app\.aplus-solution\.de([[:space:],]|$)' Caddyfile; then
    echo 'A+ domain exists with an unexpected definition; refusing automatic patch.' >&2
    exit 1
  fi
  cat >>Caddyfile <<'CADDY'
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
fi
docker exec "$CADDY_ID" caddy validate --config /etc/caddy/Caddyfile >/dev/null
docker exec "$CADDY_ID" caddy reload --config /etc/caddy/Caddyfile >/dev/null
echo APLUS_DR_INGRESS_PERSISTENT
