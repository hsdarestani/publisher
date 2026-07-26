#!/bin/sh
set -e
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
  python manage.py bootstrap_admin
fi
exec "$@"
