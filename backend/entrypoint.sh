#!/bin/sh
set -e

echo "Waiting for database..."
while ! python -c "
import socket, os
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((os.environ.get('DB_HOST', 'db'), int(os.environ.get('DB_PORT', 5432))))
s.close()
" 2>/dev/null; do
  sleep 1
done
echo "Database is ready."

echo "Running migrations..."
python manage.py migrate --noinput

echo "Loading the tagging vocabulary..."
# Non-fatal under `set -e`: a taxonomy problem must never stop the web
# container. The tagging sweep already handles a missing release.
python manage.py sync_taxonomy || echo "WARNING: taxonomy sync failed; the v2 tagger stays idle until it succeeds"

echo "Collecting static files..."
python manage.py collectstatic --noinput

exec "$@"
