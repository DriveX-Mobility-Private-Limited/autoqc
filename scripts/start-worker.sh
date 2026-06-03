#!/bin/sh
set -e

exec celery -A autoqc worker \
  --loglevel=info \
  --pool=threads \
  --concurrency=20 \
  --prefetch-multiplier=1
