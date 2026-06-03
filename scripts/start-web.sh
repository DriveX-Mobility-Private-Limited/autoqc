#!/bin/sh
set -e

exec gunicorn autoqc.wsgi:application \
  --bind "0.0.0.0:8008" \
  --workers 2 \
  --log-level "info"
