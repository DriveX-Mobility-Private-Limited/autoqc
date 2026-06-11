from celery import chord
from celery import shared_task

from autoqc.celery_app import app as celery_app
from qc.clients.nano_banana_client import NanoBananaClient
from qc.clients.s3_client import S3Client
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.constants.constants import PROCX_S3_BUCKET_PATH
from qc.constants.enums import C2CQCSource
from qc.services.vehicle_analysis_redis_service import (
    VehicleAnalysisRedisService,
)
from qc.tasks.helpers import run_gemini
from logger import get_logger

logging = get_logger()

GALAXY_RESULT_TASK_NAME = "galaxy.tasks.process_autoqc_result"
GALAXY_RESULT_QUEUE = "default"


@shared_task(bind=True, name="autoqc.tasks.image_cleanup")
def image_cleanup(
    self,  # noqa: ANN001
    image_url: str,
    target_angle: str = "",
) -> dict:
    logging.bind(
        task_id=self.request.id,
        image_url=image_url,
        target_angle=target_angle,
    ).info("Image cleanup task started")
    cleanup_result = NanoBananaClient().cleanup_image(
        image_url=image_url,
        target_angle=target_angle,
    )
    if not cleanup_result:
        logging.bind(
            task_id=self.request.id,
            image_url=image_url,
            target_angle=target_angle,
        ).error("Image cleanup task failed")
        return {
            "success": False,
            "error": "Failed to clean up image",
            "task_id": self.request.id,
            "image_url": image_url,
            "target_angle": target_angle,
        }

    result = {
        "success": True,
        "task_id": self.request.id,
        "image_url": image_url,
        "target_angle": target_angle,
        **cleanup_result,
    }
    logging.bind(
        task_id=self.request.id,
        image_url=image_url,
        target_angle=target_angle,
        skipped=cleanup_result.get("skipped"),
        model=cleanup_result.get("model"),
        has_final_orientation_analysis=bool(
            cleanup_result.get("final_orientation_analysis"),
        ),
        has_cleanup_verification=bool(cleanup_result.get("cleanup_verification")),
    ).info("Image cleanup task completed")
    return result


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
        f"Processing listing QC for {c2c_inventory_id=}, image_count={len(image_urls)}",
    )
    logging.bind(
        c2c_inventory_id=c2c_inventory_id,
        image_count=len(image_urls),
    ).info("Listing QC task started")

    if not image_urls:
        logging.bind(c2c_inventory_id=c2c_inventory_id).warning(
            "Listing QC task received no images",
        )
        publish_listing_qc_result.delay(c2c_inventory_id=c2c_inventory_id, results=[])
        return

    header = [
        process_listing_qc_image.s(
            image_url=image_url,
            image_index=image_index,
        )
        for image_index, image_url in enumerate(image_urls)
    ]
    logging.bind(
        c2c_inventory_id=c2c_inventory_id,
        image_count=len(header),
    ).info("Listing QC image chord queued")
    chord(header)(
        publish_listing_qc_result.s(c2c_inventory_id=c2c_inventory_id),
    )


@shared_task(name="autoqc.tasks.process_listing_qc_image")
def process_listing_qc_image(
    image_url: str,
    image_index: int,
) -> list[dict]:
    logging.info(
        f"Processing listing QC image for image_index={image_index}",
    )
    logging.bind(
        image_index=image_index,
        image_url=image_url,
    ).info("Listing QC image processing started")
    results = run_gemini(
        image_urls=[image_url],
        model_name=AUTO_QC_GEMINI_MODEL_NAME,
    )
    for result in results:
        result["image_index"] = image_index
    logging.bind(
        image_index=image_index,
        image_url=image_url,
        result_count=len(results),
    ).info("Listing QC image processing completed")
    return results


@shared_task(name="autoqc.tasks.publish_listing_qc_result")
def publish_listing_qc_result(
    results: list[list[dict]],
    c2c_inventory_id: int,
) -> None:
    ai_response = [
        result for image_results in results for result in (image_results or [])
    ]
    logging.bind(
        c2c_inventory_id=c2c_inventory_id,
        image_batch_count=len(results),
        ai_response_count=len(ai_response),
    ).info("Publishing listing QC result to Galaxy")

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
    logging.bind(
        c2c_inventory_id=c2c_inventory_id,
        ai_response_count=len(ai_response),
        target_task=GALAXY_RESULT_TASK_NAME,
        target_queue=GALAXY_RESULT_QUEUE,
    ).info("Published listing QC result to Galaxy")


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
        f"Starting vehicle analysis for {vehicle_id=}, {transaction_id=}, {angle=}",
    )
    logging.bind(
        task_id=self.request.id,
        vehicle_id=vehicle_id,
        transaction_id=transaction_id,
        angle=angle,
        has_image_path=bool(image_path),
        has_image_url=bool(image_url),
    ).info("Vehicle analysis task started")

    redis_service = VehicleAnalysisRedisService()
    resolved_image_url = resolve_vehicle_image_url(image_path or image_url)
    if not resolved_image_url:
        logging.bind(
            task_id=self.request.id,
            vehicle_id=vehicle_id,
            transaction_id=transaction_id,
            angle=angle,
            image_path=image_path,
            image_url=image_url,
        ).error("Vehicle analysis image URL resolution failed")
        result = {
            "success": False,
            "error": "Failed to generate S3 presigned URL for image_path",
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
    logging.bind(
        task_id=self.request.id,
        vehicle_id=vehicle_id,
        transaction_id=transaction_id,
        angle=angle,
        resolved_image_url=resolved_image_url,
        ai_response_count=len(ai_response),
    ).info("Vehicle analysis Gemini response received")

    if not ai_response:
        logging.bind(
            task_id=self.request.id,
            vehicle_id=vehicle_id,
            transaction_id=transaction_id,
            angle=angle,
        ).error("Vehicle analysis AI response unavailable")
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
    logging.bind(
        task_id=self.request.id,
        vehicle_id=vehicle_id,
        transaction_id=transaction_id,
        angle=angle,
        ai_response_count=len(ai_response),
    ).info("Vehicle analysis task completed")
    return result


def resolve_vehicle_image_url(image_path: str) -> str | None:
    if not image_path:
        return None

    logging.bind(image_path=image_path).info("Resolving vehicle image URL")
    resolved_url = S3Client().generate_presigned_get_url(image_path)
    logging.bind(
        image_path=image_path,
        resolved=bool(resolved_url),
    ).info("Vehicle image URL resolved")
    return resolved_url
