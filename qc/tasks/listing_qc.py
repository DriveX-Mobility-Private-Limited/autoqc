from celery import shared_task

from autoqc.celery_app import app as celery_app
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.constants.enums import C2CQCSource
from qc.services.vehicle_analysis_redis_service import (
    VehicleAnalysisRedisService,
)
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


@shared_task(bind=True, name="autoqc.tasks.vehicle_analysis_qc")
def vehicle_analysis_qc(
    self,  # noqa: ANN001
    vehicle_id: int,
    image_path: str,
    transaction_id: str,
    angle: str,
    image_url: str = "",
) -> dict:
    logging.info(
        f"Starting vehicle analysis for {vehicle_id=}, "
        f"{transaction_id=}, {angle=}",
    )

    redis_service = VehicleAnalysisRedisService()
    resolved_image_url = image_url or image_path
    if not resolved_image_url.startswith(("http://", "https://")):
        result = {
            "success": False,
            "error": "image_url is required when image_path is not a URL",
            "task_id": self.request.id,
            "vehicle_id": vehicle_id,
            "image_path": image_path,
            "image_url": image_url,
            "transaction_id": transaction_id,
            "angle": angle,
        }
        redis_service.save_result(transaction_id, angle, result)
        return result

    ai_response = run_gemini(
        image_urls=[resolved_image_url],
        model_name=AUTO_QC_GEMINI_MODEL_NAME,
    )

    if not ai_response:
        result = {
            "success": False,
            "error": "AI response not available",
            "task_id": self.request.id,
            "vehicle_id": vehicle_id,
            "image_path": image_path,
            "image_url": resolved_image_url,
            "transaction_id": transaction_id,
            "angle": angle,
            "raw_ai_response": [],
        }
        redis_service.save_result(transaction_id, angle, result)
        return result

    result = {
        "success": True,
        "task_id": self.request.id,
        "vehicle_id": vehicle_id,
        "image_path": image_path,
        "image_url": resolved_image_url,
        "transaction_id": transaction_id,
        "angle": angle,
        "raw_ai_response": ai_response,
    }
    redis_service.save_result(
        transaction_id,
        angle,
        {
            "result": result,
            "status": "SUCCESS",
            "task_id": self.request.id,
        },
    )
    return result
