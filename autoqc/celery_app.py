import os

from celery import Celery
from celery.signals import setup_logging
from celery.signals import worker_ready

from logger import get_logger

logging = get_logger()

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

# Keep application Loguru writes on the process stderr stream. Celery's stdout /
# stderr redirection can otherwise hide or reroute Loguru output in workers.
app.conf.worker_redirect_stdouts = False
app.conf.worker_hijack_root_logger = False


@setup_logging.connect
def _setup_loguru_logging(**kwargs):  # noqa: ANN003
    """Keep Celery from replacing the Loguru sink configured in logger.py."""


@worker_ready.connect
def _log_worker_ready(sender=None, **kwargs):  # noqa: ANN001, ANN003
    logging.bind(sender=str(sender)).info("Celery worker ready")


app.autodiscover_tasks(["qc.tasks"])
