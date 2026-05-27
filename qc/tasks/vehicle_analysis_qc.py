from celery import shared_task

from qc.clients.galaxy_client import GalaxyClient
from qc.clients.s3_client import S3Client
from qc.constants.constants import SELL_FLOW_GEMINI_MODEL_NAME
from qc.constants.enums import C2CQCStatus, C2CQCSubStatusEnum
from qc.services.redis_service import VehicleAnalysisRedisService
from qc.tasks.helpers import derive_qc_status_and_reasons, is_ev_vehicle, run_gemini
from qc.utils import generate_vehicle_name
from logger import get_logger

logging = get_logger()


@shared_task(bind=True)
def vehicle_analysis_qc_task(
    self,
    vehicle_id: int,
    image_path: str,
    transaction_id: str,
    angle: str,
) -> dict:
    logging.info(
        f"Starting vehicle analysis for vehicle_id={vehicle_id}, "
        f"image_path={image_path}, transaction_id={transaction_id}, "
        f"angle={angle}",
    )

    redis_service = VehicleAnalysisRedisService()

    # Fetch vehicle data from galaxy
    galaxy_client = GalaxyClient()
    vehicle_data = galaxy_client.get_vehicle(vehicle_id)
    if not vehicle_data:
        result = {
            "success": False,
            "error": f"Vehicle not found: {vehicle_id}",
            "task_id": self.request.id,
            "vehicle_id": vehicle_id,
            "image_path": image_path,
            "transaction_id": transaction_id,
            "angle": angle,
        }
        redis_service.save_result(transaction_id, angle, result)
        return result

    if is_ev_vehicle(vehicle_data):
        result = {
            "success": False,
            "qc_status": C2CQCStatus.FAILED.value,
            "sub_status": C2CQCSubStatusEnum.ELECTRIC_VEHICLE.value,
            "reason": "Electric vehicle not supported",
            "task_id": self.request.id,
            "vehicle_id": vehicle_id,
            "image_path": image_path,
            "transaction_id": transaction_id,
            "angle": angle,
        }
        redis_service.save_result(transaction_id, angle, result)
        return result

    # Generate presigned URL for the image
    s3_client = S3Client()
    s3_key = image_path.lstrip("/")
    ext = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else "jpeg"
    content_type_map = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    response_content_type = content_type_map.get(ext, "image/jpeg")
    presigned_url = s3_client.get_presigned_urls(
        file_names=[s3_key],
        operation="get",
        extra_params={
            "ResponseContentType": response_content_type,
        },
    )
    presigned_url = presigned_url[0]["url"] if presigned_url else None
    if not presigned_url:
        result = {
            "success": False,
            "error": "Failed to generate presigned URL",
            "task_id": self.request.id,
            "vehicle_id": vehicle_id,
            "image_path": image_path,
            "transaction_id": transaction_id,
            "angle": angle,
        }
        redis_service.save_result(transaction_id, angle, result)
        return result

    image_urls = [presigned_url]
    expected_make_model = vehicle_data.get("golden_mmv") or generate_vehicle_name(
        make=vehicle_data.get("brand", ""),
        model=vehicle_data.get("model", ""),
        variant=vehicle_data.get("variant"),
    )

    registration_number = vehicle_data.get("registration_number", "")

    ai_response = run_gemini(
        image_urls=image_urls,
        expected_make_model=expected_make_model,
        model_name=SELL_FLOW_GEMINI_MODEL_NAME,
    )

    if not ai_response:
        result = {
            "success": False,
            "error": "AI response not available",
            "qc_status": C2CQCStatus.NEEDS_REVIEW.value,
            "sub_status": C2CQCSubStatusEnum.AI_RESPONSE_NOT_AVAILABLE.value,
            "task_id": self.request.id,
            "vehicle_id": vehicle_id,
            "image_path": image_path,
            "transaction_id": transaction_id,
            "angle": angle,
        }
        redis_service.save_result(transaction_id, angle, result)
        return result

    qc_status, sub_statuses, selected_plate = derive_qc_status_and_reasons(
        results=ai_response,
        registration_number=registration_number,
        dry_run=True,
    )

    logging.info(
        f"Vehicle analysis results - Status: {qc_status}, "
        f"Sub statuses: {sub_statuses}, Selected plate: {selected_plate}",
    )

    result = {
        "success": True,
        "task_id": self.request.id,
        "vehicle_id": vehicle_id,
        "image_path": image_path,
        "transaction_id": transaction_id,
        "angle": angle,
        "qc_status": qc_status,
        "sub_statuses": sub_statuses,
        "selected_plate": selected_plate,
        "expected_registration": registration_number,
        "expected_make_model": expected_make_model,
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
