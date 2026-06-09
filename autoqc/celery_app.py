import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autoqc.settings")

app = Celery("autoqc")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autoqc workers consume the `autoqc` queue by default; galaxy publishes here.
app.conf.task_default_queue = "autoqc"

# Route published task names to the right queues:
# - Our own task lands on `autoqc` (where our workers consume).
# - Replies to galaxy go onto galaxy's `default` queue.
app.conf.task_routes = {
    "autoqc.tasks.process_listing_qc": {"queue": "autoqc"},
    "autoqc.tasks.process_listing_qc_image": {"queue": "autoqc"},
    "autoqc.tasks.publish_listing_qc_result": {"queue": "autoqc"},
    "galaxy.tasks.process_autoqc_result": {"queue": "default"},
}

app.autodiscover_tasks(["qc.tasks"])
