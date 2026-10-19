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
python manage.py sync_taxonomy

echo "Collecting static files..."
python manage.py collectstatic --noinput

exec "$@"
