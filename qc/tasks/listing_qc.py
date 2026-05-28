from celery import shared_task

from autoqc.celery_app import app as celery_app
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.constants.enums import C2CQCSource
from qc.tasks.helpers import run_gemini
from logger import get_logger

logging = get_logger()

GALAXY_RESULT_TASK_NAME = "galaxy.tasks.process_autoqc_result"
GALAXY_RESULT_QUEUE = "default"


@shared_task(name="autoqc.tasks.process_listing_qc")
def process_listing_qc(
    c2c_inventory_id: int,
    image_urls: list[str],
) -> None:
    """
    Consume a listing-QC job published by galaxy, run Gemini, and publish
    the raw response back to galaxy. Galaxy owns QC verdict derivation and
    persistence (see AutoQCResultProcessor).
    """
    logging.info(
        f"Processing listing QC for {c2c_inventory_id=}, "
        f"image_count={len(image_urls)}",
    )

    ai_response = run_gemini(
        image_urls=image_urls,
        model_name=AUTO_QC_GEMINI_MODEL_NAME,
    )

    celery_app.send_task(
        GALAXY_RESULT_TASK_NAME,
        kwargs={
            "c2c_inventory_id": c2c_inventory_id,
            "raw_ai_response": ai_response or [],
            "qc_source": C2CQCSource.AI.value,
        },
        queue=GALAXY_RESULT_QUEUE,
    )
    logging.info(
        f"Published autoqc result back to galaxy for {c2c_inventory_id=}",
    )
