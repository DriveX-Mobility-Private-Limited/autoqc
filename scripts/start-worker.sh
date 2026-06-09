#!/bin/sh
set -e

exec celery -A autoqc worker \
  --loglevel=info \
  --pool=gevent \
  --concurrency=50 \
  --prefetch-multiplier=1
