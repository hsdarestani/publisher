#!/usr/bin/env bash
# Local, versioned restore points. Never alter the streaming replica.
set -euo pipefail
umask 077
exec 9>/run/aplus-standby-snapshot.lock
flock -n 9 || { echo "Another A+ snapshot is already running"; exit 0; }
D=/opt/aplussolution-standby
OUT="$D/snapshots"
test ! -L "$D" && test ! -L "$OUT"
test -s "$D/recovery/aplussolution.env"
test -s "$D/recovery/app-source.tgz"
test -d "$D/media"
mkdir -p -m 700 "$OUT"
chmod 700 "$OUT"
cd "$D"
RECOVERY="$(docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select pg_is_in_recovery()"' </dev/null | tr -d '[:space:]')"
if [ "$RECOVERY" != t ]; then
  test "$RECOVERY" = f && test -f "$D/failover-active" || {
    echo "Refusing backup: unexpected database role without confirmed failover" >&2
    exit 1
  }
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d "$OUT/.snapshot-XXXXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT
docker compose exec -T db sh -lc 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-sync' </dev/null > "$TMP/database.dump"
test -s "$TMP/database.dump"
docker run --rm --entrypoint pg_restore -v "$TMP:/snap:ro" postgres:16-alpine --list /snap/database.dump >/dev/null
ionice -c3 nice -n 10 tar -C "$D" -czf "$TMP/media.tar.gz" media
cp "$D/recovery/aplussolution.env" "$TMP/aplussolution.env"
cp "$D/recovery/app-source.tgz" "$TMP/app-source.tgz"
{
  printf 'timestamp_utc=%s\n' "$STAMP"
  printf 'source=postgresql_hot_standby\n'
  printf 'role=read_only_replica\n'
  printf 'media_sync_unix_time=%s\n' "$(stat -c %Y "$D/last-file-sync-success")"
  printf 'database_size_bytes=%s\n' "$(stat -c %s "$TMP/database.dump")"
} > "$TMP/manifest.txt"
(cd "$TMP"; sha256sum database.dump media.tar.gz aplussolution.env app-source.tgz manifest.txt > SHA256SUMS; sha256sum --check --status SHA256SUMS)
tar -tzf "$TMP/media.tar.gz" >/dev/null
tar -tzf "$TMP/app-source.tgz" >/dev/null
FINAL="$OUT/backup-$STAMP"
mv "$TMP" "$FINAL"
trap - EXIT
chmod -R go-rwx "$FINAL"
find "$OUT" -mindepth 1 -maxdepth 1 -type d -name 'backup-20????????T??????Z' -mtime +13 ! -path "$FINAL" -exec rm -rf -- {} +
echo "SNAPSHOT_CREATED $STAMP"
echo "SNAPSHOT_DATABASE_ARCHIVE_VERIFIED"
echo "SNAPSHOT_MEDIA_AND_CONFIG_CHECKSUMS_VERIFIED"
echo "SNAPSHOT_COUNT $(find "$OUT" -mindepth 1 -maxdepth 1 -type d -name 'backup-*' | wc -l)"
