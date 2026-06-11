#!/bin/sh
set -e

exec celery -A autoqc worker \
  --loglevel=info \
  --queues=autoqc \
  --pool=gevent \
  --concurrency=50 \
  --prefetch-multiplier=1
