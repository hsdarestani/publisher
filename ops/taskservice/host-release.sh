#!/usr/bin/env bash
# Runs on the existing Publisher host using its own Compose configuration.
set -euo pipefail
umask 077
phase=${1:?}
revision=${2:-}
cd /opt/taskservice
exec 9>/run/lock/taskservice-release.lock
flock -n 9 || { echo 'A TaskService release operation is active'; exit 1; }
compose() { docker compose -p taskservice -f compose.yaml -f compose-lowmem.experimental.yaml "$@"; }
sql() { compose exec -T db psql -X -qAt -v ON_ERROR_STOP=1 -U postgres -d "$1" "${@:2}"; }
die() { echo "$*" >&2; exit 1; }
config=/etc/taskservice/release.env
load_backup_config() {
  [[ -f $config && ! -L $config && $(stat -c '%u:%a' "$config") =~ ^0:(400|600)$ ]] ||
    die 'BACKUP_GATE: approved recovery configuration unavailable'
  # Root-owned operational configuration. Never print its contents.
  source "$config"
  : "${TASKSERVICE_BACKUP_MOUNT:?}" "${TASKSERVICE_BACKUP_DIR:?}" "${TASKSERVICE_AGE_RECIPIENT:?}" "${TASKSERVICE_RECOVERY_IDENTITY:?}"
  local mount dest
  mount=$(realpath -e "$TASKSERVICE_BACKUP_MOUNT")
  dest=$(realpath -e "$TASKSERVICE_BACKUP_DIR")
  [[ $mount != / && ( $dest == "$mount" || $dest == "$mount/"* ) ]] || die 'BACKUP_GATE: destination outside approved mount'
  [[ $(findmnt -n -T "$dest" -o TARGET) == "$mount" ]] || die 'BACKUP_GATE: recovery mount unavailable'
  [[ $(findmnt -n -T "$dest" -o FSTYPE) =~ ^(nfs|nfs4|cifs|fuse.sshfs|ceph)$ ]] || die 'BACKUP_GATE: off-host storage not verified'
  [[ -r $TASKSERVICE_RECOVERY_IDENTITY ]] || die 'BACKUP_GATE: recovery identity unavailable'
  command -v age >/dev/null
}
ready() {
  compose exec -T api sh -c 'curl -fsS --max-time 8 -H "Host: $TASKSERVICE_HEALTH_HOST" http://127.0.0.1:8080/health/ready' >/dev/null &&
  curl -fsS --max-time 10 https://taskservice.smarbiz.sbs/api/v1/session >/dev/null &&
  (cd /opt/aplus-publisher && docker compose exec -T web curl -fsS --max-time 8 http://127.0.0.1:8000/healthz/ >/dev/null)
}
check_capacity() {
  compose config -q
  for svc in db scanner api; do
    local cid health
    cid=$(compose ps -q "$svc")
    [[ -n $cid ]] || die "READINESS_GATE: $svc is absent"
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")
    printf 'SERVICE=%s HEALTH=%s\n' "$svc" "$health"
    [[ $health == healthy ]] || die "READINESS_GATE: $svc requires recovery"
  done
  local bytes headroom group limit current mem free_db free_image dbpath
  bytes=$(sql taskservice -c "SELECT pg_database_size(current_database())")
  mem=$(( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) * 1024 ))
  group=$(systemctl show taskservice.slice -p ControlGroup --value)
  [[ $group == /taskservice.slice ]] || die 'CAPACITY_GATE: isolation unavailable'
  limit=$(cat "/sys/fs/cgroup$group/memory.max")
  current=$(cat "/sys/fs/cgroup$group/memory.current")
  [[ $limit =~ ^[0-9]+$ ]] || die 'CAPACITY_GATE: finite aggregate limit required'
  headroom=$((limit - current))
  dbpath=$(docker inspect "$(compose ps -q db)" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Source}}{{end}}{{end}}')
  [[ -d $dbpath ]] || die 'CAPACITY_GATE: database volume unavailable'
  free_db=$(df -PB1 "$dbpath" | awk 'NR==2 {print $4}')
  free_image=$(df -PB1 "$(docker info --format '{{.DockerRootDir}}')" | awk 'NR==2 {print $4}')
  printf 'HOST_AVAILABLE_BYTES=%s SLICE_HEADROOM_BYTES=%s DB_BYTES=%s DB_DISK_AVAILABLE_BYTES=%s IMAGE_DISK_AVAILABLE_BYTES=%s\n' "$mem" "$headroom" "$bytes" "$free_db" "$free_image"
  # Cover a disposable restore, PostgreSQL WAL, and the capped migration container.
  ((free_db > 3 * bytes + 256 * 1024 * 1024 && mem > 256 * 1024 * 1024 && headroom > 256 * 1024 * 1024)) ||
    die 'CAPACITY_GATE: insufficient current restore or migration headroom'
}
backup_and_restore() (
  set -euo pipefail
  load_backup_config
  local bytes free tmp scratch created=false
  bytes=$(sql taskservice -c "SELECT pg_database_size(current_database())")
  free=$(df -PB1 "$TASKSERVICE_BACKUP_DIR" | awk 'NR==2 {print $4}')
  ((free > bytes + 64 * 1024 * 1024)) || die 'BACKUP_GATE: recovery destination has insufficient free space'
  tmp=$(mktemp -d "$TASKSERVICE_BACKUP_DIR/taskservice-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX")
  scratch="ts_restore_$(cat /proc/sys/kernel/random/uuid | tr -d -)"
  cleanup_restore() {
    if [[ $created == true ]]; then sql postgres -c "DROP DATABASE $scratch" >/dev/null; fi
  }
  trap cleanup_restore EXIT
  compose exec -T db pg_dump -U postgres -Fc -d taskservice | age -r "$TASKSERVICE_AGE_RECIPIENT" -o "$tmp/postgres.age"
  compose exec -T api tar -C /var/lib/taskservice/keys -cf - . | age -r "$TASKSERVICE_AGE_RECIPIENT" -o "$tmp/keys.age"
  (cd "$tmp" && sha256sum postgres.age keys.age > SHA256SUMS && sha256sum -c SHA256SUMS)
  # Verify an actual keyring is recoverable, without printing key material or extracting it.
  age -d -i "$TASKSERVICE_RECOVERY_IDENTITY" "$tmp/keys.age" | tar -tf - |
    awk '/(^|\/)key-[^/]+\.xml$/ {found=1} END {exit !found}'
  sql postgres -c "CREATE DATABASE $scratch TEMPLATE template0" >/dev/null
  created=true
  age -d -i "$TASKSERVICE_RECOVERY_IDENTITY" "$tmp/postgres.age" |
    compose exec -T db pg_restore -U postgres --exit-on-error --single-transaction --dbname="$scratch"
  sql "$scratch" <<'SQL'
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM ts.tenants) OR NOT EXISTS (SELECT FROM public."__EFMigrationsHistory") THEN
   RAISE EXCEPTION 'Restored schema or company records are missing';
 END IF;
 IF NOT (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='ts.requests'::regclass) THEN
   RAISE EXCEPTION 'Tenant isolation missing on restored requests';
 END IF;
END $$;
SET ROLE taskservice_api;
DO $$ BEGIN
 IF EXISTS (SELECT FROM ts.requests) THEN RAISE EXCEPTION 'Unscoped restored data exposed'; END IF;
END $$;
SQL
  date -u +%FT%TZ > "$tmp/RESTORE_VERIFIED"
  echo "BACKUP_RESTORE=verified ARCHIVE=$(basename "$tmp")"
)
capture_previous() {
  local cid
  cid=$(compose ps -q api)
  [[ -n $cid ]] || die 'API container missing'
  [[ $(docker inspect -f '{{.State.Running}}' "$cid") == true ]] || die 'API is down'
}
wait_ready() {
  for _ in {1..25}; do
    if ready && [[ $(docker inspect -f '{{.State.Running}}' "$(compose ps -q worker)") == true ]]; then return 0; fi
    sleep 3
  done
  return 1
}
rollback() {
  test -f "$release_dir/dotenv"
  grep -Fxq "TASKSERVICE_IMAGE=taskservice:v3-$revision" .env || die 'Rollback target changed'
  install -m 0600 "$release_dir/dotenv" .env.rollback
  mv -fT .env.rollback .env
  docker compose -p taskservice -f compose.yaml -f compose-lowmem.experimental.yaml -f "$release_dir/previous-images.yaml" up -d --no-deps api worker
  wait_ready
  echo 'ROLLBACK=previous application images restored and verified'
}
case "$phase" in
  preflight|rehearse|release|rollback) ;;
  *) die 'Unknown release operation';;
esac
if [[ $phase == release || $phase == rollback ]]; then
  [[ $revision =~ ^[a-f0-9]{40}$ ]] || die 'Invalid revision'
  release_dir="/opt/taskservice/releases/$revision"
fi
if [[ $phase == rollback ]]; then rollback; exit; fi
check_capacity
capture_previous
ready || die 'READINESS_GATE: TaskService or Publisher baseline health failed'
load_backup_config
echo 'PREFLIGHT=passed'
if [[ $phase == preflight ]]; then exit; fi
backup_and_restore
if [[ $phase == rehearse ]]; then exit; fi
target="taskservice:v3-$revision"
[[ $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$target") == "$revision" ]] || die 'Release image mismatch'
install -d -m 0700 "$release_dir"
# Preserve the original rollback point across retries of the same revision.
if ! grep -Fxq "TASKSERVICE_IMAGE=$target" .env; then
  install -m 0600 .env "$release_dir/dotenv"
  # The pilot can have different API and worker revisions. Retain both exact images.
  {
    echo 'services:'
    for svc in api worker; do
      previous=$(docker inspect -f '{{.Image}}' "$(compose ps -q "$svc")")
      [[ $previous =~ ^sha256:[a-f0-9]{64}$ ]] || die 'Previous image identity unavailable'
      docker tag "$previous" "taskservice:rollback-$revision-$svc"
      printf '  %s:\n    image: taskservice:rollback-%s-%s\n' "$svc" "$revision" "$svc"
    done
  } > "$release_dir/previous-images.yaml"
fi
test -s "$release_dir/dotenv"
TASKSERVICE_IMAGE="$target" compose run --rm -T --no-deps migrate
# Migration precedes activation. Both images must match the schema.
python3 - "$target" <<'PY'
from pathlib import Path
import os, re, sys
path = Path('.env')
data = path.read_bytes()
data, count = re.subn(rb'^TASKSERVICE_IMAGE=[^\r\n]+', b'TASKSERVICE_IMAGE=' + sys.argv[1].encode('ascii'), data, flags=re.M)
if count != 1:
    raise SystemExit('Expected exactly one application image setting')
out = Path('.env.release')
out.write_bytes(data)
os.chmod(out, 0o600)
out.replace(path)
PY
if ! compose up -d --no-deps api worker || ! wait_ready; then
  rollback
  die 'New release failed its health checks'
fi
for svc in api worker; do
  [[ $(docker inspect -f '{{.Image}}' "$(compose ps -q "$svc")") == "$(docker image inspect -f '{{.Id}}' "$target")" ]] || { rollback; die 'Running image mismatch'; }
done
echo "RELEASE_REVISION=$revision"
