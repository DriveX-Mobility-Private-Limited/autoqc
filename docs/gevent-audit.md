# Gevent Worker Audit

## Decision

AutoQC Celery workers use `--pool=gevent --concurrency=20` for Gemini jobs.
The workload is mostly outbound HTTP I/O, so greenlet concurrency should improve
throughput without increasing process count.

## Third-party library audit

- `celery`: supports the `gevent` pool. Celery applies gevent/eventlet
  monkey-patching early when the pool is selected from the CLI.
- `requests` / `urllib3`: acceptable for this worker because gevent
  monkey-patches sockets before task modules are imported.
- `django-redis` / `redis`: acceptable for the same socket monkey-patching
  reason. Keep Redis operation timeouts configured at the infrastructure layer.
- `langfuse`: used for prompt fetches before Gemini calls. Treat as network I/O;
  it should be cooperative after gevent patching.
- `pydantic`, `zstandard`, `environs`: CPU/local work only. They do not affect
  gevent scheduling materially for the current task shape.
- `pillow`, `pillow-heif`, `pillow-avif-plugin`, `boto3`: not on the current
  Gemini task hot path. If image processing or S3 work is reintroduced in Celery,
  reassess because CPU-heavy image work is a poor fit for gevent.

## Caveats

- Celery gevent workers do not support all prefork features, notably soft time
  limits. The Gemini client must keep explicit request timeouts.
- CPU-heavy work will block the gevent worker. Keep Celery tasks I/O-bound or
  move CPU-heavy tasks to a separate prefork worker.
we  latency, worker memory, and task retry/failure rates.
