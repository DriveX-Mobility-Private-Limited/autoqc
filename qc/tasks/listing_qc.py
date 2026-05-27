from celery import shared_task

from qc.clients.galaxy_client import GalaxyClient
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.constants.enums import C2CQCSource, C2CQCStatus, C2CQCSubStatusEnum
from qc.tasks.helpers import derive_qc_status_and_reasons, is_ev_vehicle, run_gemini
from logger import get_logger

logging = get_logger()


@shared_task(bind=True)
def listing_qc_task(
    self,
    c2c_inventory_id: int,
    callback_url: str,
) -> bool:
    logging.info(
        f"Starting listing QC for c2c_inventory_id={c2c_inventory_id}",
    )

    galaxy_client = GalaxyClient()

    # Fetch inventory data from galaxy
    inventory_data = galaxy_client.get_inventory(c2c_inventory_id)
    if not inventory_data:
        logging.error(
            f"Failed to fetch inventory {c2c_inventory_id} from galaxy",
        )
        return False

    # Check if already passed
    if inventory_data.get("qc_status") == C2CQCStatus.PASSED.value:
        logging.info(
            f"Inventory {c2c_inventory_id} already passed QC, skipping",
        )
        return True

    # Check if EV
    if is_ev_vehicle(inventory_data):
        payload = {
            "c2c_inventory_id": c2c_inventory_id,
            "qc_status": C2CQCStatus.FAILED.value,
            "sub_statuses": [C2CQCSubStatusEnum.ELECTRIC_VEHICLE.value],
            "selected_plate": None,
            "raw_ai_response": [],
            "qc_source": C2CQCSource.AI.value,
        }
        galaxy_client.post_qc_result(callback_url, payload)
        return False

    # Get images (prefer DMS images for AI processing)
    image_urls = inventory_data.get("dms_image_urls") or inventory_data.get(
        "image_urls", [],
    )
    if not image_urls:
        logging.error(
            f"No images found for inventory {c2c_inventory_id}",
        )
        return False

    expected_make_model = inventory_data.get("expected_make_model", "")
    registration_number = inventory_data.get("registration_number", "")

    # Call Gemini
    ai_response = run_gemini(
        image_urls=image_urls,
        expected_make_model=expected_make_model,
        model_name=AUTO_QC_GEMINI_MODEL_NAME,
    )

    if not ai_response:
        logging.error("AI response not available")
        payload = {
            "c2c_inventory_id": c2c_inventory_id,
            "qc_status": C2CQCStatus.NEEDS_REVIEW.value,
            "sub_statuses": [
                C2CQCSubStatusEnum.AI_RESPONSE_NOT_AVAILABLE.value,
            ],
            "selected_plate": None,
            "raw_ai_response": [],
            "qc_source": C2CQCSource.AI.value,
        }
        galaxy_client.post_qc_result(callback_url, payload)
        return False

    # Derive QC status
    qc_status, sub_statuses, selected_plate = derive_qc_status_and_reasons(
        results=ai_response,
        registration_number=registration_number,
    )

    logging.info(
        f"Listing QC results - inventory={c2c_inventory_id}, "
        f"status={qc_status}, sub_statuses={sub_statuses}, "
        f"plate={selected_plate}",
    )

    # Post result back to galaxy webhook
    payload = {
        "c2c_inventory_id": c2c_inventory_id,
        "qc_status": qc_status,
        "sub_statuses": sub_statuses,
        "selected_plate": selected_plate,
        "raw_ai_response": ai_response,
        "qc_source": C2CQCSource.AI.value,
    }

    success = galaxy_client.post_qc_result(callback_url, payload)
    if not success:
        logging.error(
            f"Failed to post QC result for inventory {c2c_inventory_id}",
        )

    return success
