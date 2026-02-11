#!/bin/sh
set -e

echo "=== Ejecutando collectstatic ==="
python manage.py collectstatic --noinput

echo "=== Ejecutando migrate ==="
python manage.py migrate --noinput

echo "=== Arrancando Gunicorn ==="
exec gunicorn billing_ai.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 60 \
    --log-level info
