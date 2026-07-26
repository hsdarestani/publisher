#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/aplus-publisher"
ARCHIVE="${1:-/tmp/aplus-publisher.tar.gz}"
OVERRIDES="${2:-/tmp/aplus-publisher-overrides.env}"
BOOTSTRAP_MARKER="$APP_DIR/.bootstrap_complete"
mkdir -p "$APP_DIR"
find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name '.env' ! -name '.bootstrap_complete' -exec rm -rf {} +
tar -xzf "$ARCHIVE" -C "$APP_DIR"
cd "$APP_DIR"

install_docker_stack() {
  apt-get update
  if DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 ca-certificates curl openssl; then
    systemctl enable --now docker
    return 0
  fi

  # Fallback to Docker's official apt repository when the Ubuntu mirror does not
  # expose the Compose v2 package.
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl openssl
  apt-get remove -y docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc >/dev/null 2>&1 || true
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  install_docker_stack
fi

if [ ! -f .env ]; then
  DJANGO_SECRET_KEY="$(openssl rand -hex 48)"
  POSTGRES_PASSWORD="$(openssl rand -hex 24)"
  ENCRYPTION_KEY="$(python3 - <<'PY'
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
  )"
  cat > .env <<ENV
DOMAIN=publisher.smarbiz.sbs
PUBLIC_URL=https://publisher.smarbiz.sbs
DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY
ENCRYPTION_KEY=$ENCRYPTION_KEY
DEBUG=0
ALLOWED_HOSTS=publisher.smarbiz.sbs,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://publisher.smarbiz.sbs
POSTGRES_DB=publisher
POSTGRES_USER=publisher
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
TIME_ZONE=Europe/Berlin
ENV
fi

# Optional values from GitHub secrets. Empty lines are ignored, so deployment never
# depends on these variables being present.
if [ -f "$OVERRIDES" ]; then
  while IFS='=' read -r key value; do
    [ -z "$key" ] && continue
    [ -z "$value" ] && continue
    grep -v "^${key}=" .env > .env.tmp || true
    printf '%s=%s\n' "$key" "$value" >> .env.tmp
    mv .env.tmp .env
  done < "$OVERRIDES"
fi
chmod 600 .env

# A failed first installation may leave partially-created PostgreSQL objects. There
# is no user data before this marker exists, so reset all first-boot volumes once.
# The marker is preserved across releases and makes this branch permanently inert
# after the first successful health check.
if [ ! -f "$BOOTSTRAP_MARKER" ]; then
  echo "Preparing a clean first-install database..."
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
fi

docker compose build --pull
docker compose up -d --remove-orphans

# The web entrypoint owns migrations, static collection and administrator updates.
echo "Waiting for application health and startup migrations..."
for attempt in $(seq 1 45); do
  if docker compose exec -T web curl -fsS --max-time 5 http://127.0.0.1:8000/healthz/ >/dev/null 2>&1; then
    if docker compose exec -T web sh -lc '[ -n "${ADMIN_EMAIL:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]'; then
      docker compose exec -T web python manage.py shell -c '
import os
from django.contrib.auth import authenticate
user = authenticate(username=os.environ["ADMIN_EMAIL"], password=os.environ["ADMIN_PASSWORD"])
assert user is not None and user.is_active and user.is_superuser, "Configured administrator authentication failed"
print("Configured administrator authentication verified.")
'
    else
      echo "Administrator secrets are not both configured; login verification skipped."
    fi
    touch "$BOOTSTRAP_MARKER"
    chmod 600 "$BOOTSTRAP_MARKER"
    echo "A+ Publisher is healthy."
    docker image prune -f >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 4
done

docker compose ps
docker compose logs --tail=200 web worker beat caddy
exit 1
