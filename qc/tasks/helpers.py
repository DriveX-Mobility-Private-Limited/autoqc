import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from celery import shared_task
from django.conf import settings
from langfuse import Langfuse

from qc.clients.gemini_client import GeminiClient
from qc.constants.constants import (
    AUTO_QC_GEMINI_MODEL_NAME,
    C2C_INELIGIBLE_FUEL_TYPE,
    CONFIDENCE_THRESHOLD,
    IMAGE_PATH_PREFIX,
    THRESHOLD,
)
from qc.constants.enums import C2CQCStatus, C2CQCSubStatusEnum
from qc.services.image_service import ImageService
from qc.utils import is_valid_reg_no
from logger import get_logger

logging = get_logger()

DEFAULT_PROMPT = (
    "Analyze the provided vehicle images. For each image, extract the "
    "license plate number if visible, determine the view angle, and check "
    "for image quality issues."
)


def _get_langfuse() -> Langfuse:
    return Langfuse(
        host=settings.LANGFUSE_HOST,
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
    )


def _get_prompt() -> str:
    label = "latest" if settings.DEBUG else "production"
    try:
        langfuse = _get_langfuse()
        return langfuse.get_prompt(
            "license-plate-extraction-batch", label=label,
        ).prompt
    except Exception as e:
        logging.warning(f"Failed to fetch Langfuse prompt: {e}. Using default.")
        return DEFAULT_PROMPT


# ── Gemini execution ────────────────────────────────────────────────


def _run_batch(
    batch_urls: list[str],
    batch_offset: int,
    prompt: str,
    expected_make_model: str,
    model_name: str,
) -> list[dict]:
    client = GeminiClient(model_name=model_name)
    results = client.generate(
        prompt=prompt,
        image_urls=batch_urls,
        expected_make_model=expected_make_model,
    )
    for result in results:
        result["image_index"] += batch_offset
    return results


def run_gemini(
    image_urls: list[str],
    expected_make_model: str | None,
    model_name: str,
) -> list[dict]:
    if not image_urls:
        return []

    prompt = _get_prompt()
    make_model = expected_make_model or ""
    batch_size = settings.GEMINI_BATCH_SIZE

    if len(image_urls) <= batch_size:
        try:
            return _run_batch(image_urls, 0, prompt, make_model, model_name)
        except Exception:
            logging.exception("Gemini invocation failed")
            return []

    batches = [
        (image_urls[i : i + batch_size], i)
        for i in range(0, len(image_urls), batch_size)
    ]
    max_workers = min(settings.GEMINI_MAX_WORKERS, len(batches))

    logging.info(
        f"Processing {len(image_urls)} images in {len(batches)} "
        f"batches with {max_workers} threads",
    )

    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_batch, urls, offset, prompt, make_model, model_name,
            ): offset
            for urls, offset in batches
        }
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception:
                logging.exception(
                    f"Gemini batch failed (offset={futures[future]})",
                )

    all_results.sort(key=lambda r: r.get("image_index", 0))
    return all_results


@shared_task
def run_gemini_task(
    image_urls: list[str],
    expected_make_model: str | None,
    registration_number: str,
) -> dict:
    response = run_gemini(
        image_urls=image_urls,
        expected_make_model=expected_make_model,
        model_name=AUTO_QC_GEMINI_MODEL_NAME,
    )
    corrected_keys = fix_rotation(response)
    qc_status, sub_statuses, selected_plate = derive_qc_status_and_reasons(
        results=response,
        registration_number=registration_number,
    )
    return {
        "qc_status": qc_status,
        "sub_statuses": sub_statuses,
        "selected_plate": selected_plate,
        "raw_ai_response": response,
        "corrected_keys": corrected_keys,
    }


# ── QC status derivation ───────────────────────────────────────────


def derive_qc_status_and_reasons(
    results: list[dict],
    registration_number: str,
    *,
    dry_run: bool = False,
) -> tuple[str, list[str], str | None]:
    sub_statuses: list[str] = []

    non_odometer = [r for r in results if r.get("view_label") != "odometer"]
    odometer = [r for r in results if r.get("view_label") == "odometer"]

    is_rotated = any(r.get("is_rotated") for r in non_odometer)
    any_ai_generated = any(r.get("is_ai_generated") for r in non_odometer)
    is_screenshot = any(r.get("is_screenshot") for r in non_odometer)
    is_out_of_frame = any(
        r.get("is_images_out_of_frame") for r in non_odometer
    )
    unclear_count = sum(1 for r in non_odometer if r.get("images_unclear"))
    bad_lighting_count = sum(
        1 for r in non_odometer if r.get("images_bad_lighting")
    )

    normalized_rc = (is_valid_reg_no(registration_number) or "").upper()
    valid_plates = [
        p
        for r in non_odometer
        if r.get("success")
        if (p := (is_valid_reg_no(r.get("license_plate") or "") or ""))
    ]

    if not valid_plates:
        return (
            C2CQCStatus.NEEDS_REVIEW.value,
            [C2CQCSubStatusEnum.REGISTRATION_NUMBER_NOT_FOUND.value],
            None,
        )

    if dry_run:
        selected_plate = valid_plates[0]
    elif not normalized_rc or normalized_rc not in valid_plates:
        return (
            C2CQCStatus.QUERY_RAISED.value,
            [C2CQCSubStatusEnum.IMAGE_REGISTRATION_NUMBER_MISMATCH.value],
            valid_plates[0],
        )
    else:
        selected_plate = normalized_rc

    status_checks = [
        (is_rotated, C2CQCSubStatusEnum.IMAGE_ROTATION_ISSUE, C2CQCStatus.NEEDS_REVIEW),
        (any_ai_generated, C2CQCSubStatusEnum.IMAGE_AI_GENERATED, C2CQCStatus.QUERY_RAISED),
        (is_screenshot, C2CQCSubStatusEnum.IMAGE_SCREENSHOT, C2CQCStatus.QUERY_RAISED),
        (is_out_of_frame, C2CQCSubStatusEnum.IMAGE_OUT_OF_FRAME, C2CQCStatus.QUERY_RAISED),
        (unclear_count > THRESHOLD, C2CQCSubStatusEnum.IMAGE_UNCLEAR, C2CQCStatus.QUERY_RAISED),
        (bad_lighting_count > THRESHOLD, C2CQCSubStatusEnum.IMAGE_BAD_LIGHTING, C2CQCStatus.QUERY_RAISED),
    ]

    final_status = C2CQCStatus.QUERY_RAISED
    for condition, sub_status, qc_status in status_checks:
        if condition:
            sub_statuses.append(sub_status.value)
            if qc_status == C2CQCStatus.NEEDS_REVIEW:
                final_status = C2CQCStatus.NEEDS_REVIEW

    if sub_statuses:
        return (final_status.value, sub_statuses, selected_plate)

    return (C2CQCStatus.PASSED.value, [], selected_plate)


# ── Image rotation ──────────────────────────────────────────────────


def fix_rotation(ai_response: list[dict]) -> list[str] | None:
    rotated = [
        {
            "image_url": r["image_url"],
            "rotation_angle": int(r["rotation_angle"]),
            "image_index": r["image_index"],
        }
        for r in ai_response
        if r.get("is_rotated") and r.get("rotation_angle", 0) != 0
    ]
    if not rotated:
        return None

    service = ImageService()
    corrected_keys = []

    for info in rotated:
        if service.rotate_and_upload(
            image_url=info["image_url"],
            rotation_angle=info["rotation_angle"],
        ):
            key = info["image_url"].replace(IMAGE_PATH_PREFIX, "")
            corrected_keys.append(key)
            logging.info(f"Successfully corrected image: {key}")
        else:
            logging.error(f"Failed to rotate image {info['image_url']}")

    return corrected_keys or None


# ── Utilities ───────────────────────────────────────────────────────


def is_ev_vehicle(vehicle_data: dict) -> bool:
    return vehicle_data.get("is_ev", False)
