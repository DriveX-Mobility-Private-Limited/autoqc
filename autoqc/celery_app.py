import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autoqc.settings")

app = Celery("autoqc")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["qc.tasks"])
