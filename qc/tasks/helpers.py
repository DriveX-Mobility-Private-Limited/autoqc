from django.conf import settings
from langfuse import Langfuse

from qc.clients.gemini_client import GeminiClient
from logger import get_logger

logging = get_logger()

DEFAULT_PROMPT = """
You are an expert two-wheeler inspection AI. Analyze only the primary
two-wheeler intended for inspection. Ignore background vehicles unless they
obstruct the primary vehicle or affect image clarity.

This is a sanity-check QC pass for image quality and downstream background
removal. Be strict about issues that would make a background-removal service
fail or remove parts of the primary vehicle.

For each image, extract:
- license plate text exactly as visible, preserving spaces/dashes/case
- odometer reading when visible
- view label: front, rear, left, right, odometer, or other
- people and other vehicles visible in the background
- authenticity, orientation, framing, clarity, lighting, and background-removal
  suitability

Rules:
- Set license_plate to null if no plate is readable.
- For odometer images, set is_odometer_reading_on true only when the odometer
  number is clearly readable. Return odometer_reading as an integer when
  possible and odometer_reading_text exactly as seen.
- Set is_rotated true only when the image is not upright for natural human
  viewing. rotation_angle must be 0, 90, 180, or 270 and represents the
  anti-clockwise correction needed to make the image upright.
- Set is_images_out_of_frame true for cropped, zoomed-in, obstructed, or
  incomplete vehicle/odometer/license-plate views. Also set it true when
  background-removal would likely remove part of the primary two-wheeler or
  fail because another object/person/vehicle is touching, overlapping, or
  tightly adjacent to the primary vehicle.
- Set images_unclear true for blur, low resolution, or unreadable critical
  details.
- Set images_bad_lighting true for darkness, overexposure, glare, or shadows
  that prevent reading key details.
- Set is_screenshot true for screenshots and is_ai_generated true for synthetic
  images. If uncertain, choose the most likely value.

Return strict JSON only:
{
  "results": [
    {
      "success": true,
      "license_plate": "KA 03 HY 6692",
      "error": null,
      "image_index": 0,
      "view_label": "front",
      "people_in_background": 0,
      "vehicles_in_background": 1,
      "confidence": 0.95,
      "is_ai_generated": false,
      "is_screenshot": false,
      "is_rotated": false,
      "rotation_angle": 0,
      "is_images_out_of_frame": false,
      "images_unclear": false,
      "is_odometer_reading_on": false,
      "odometer_reading": null,
      "odometer_reading_text": null,
      "images_bad_lighting": false
    }
  ]
}
"""


def _get_langfuse() -> Langfuse:
    return Langfuse(
        host=settings.LANGFUSE_HOST,
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
    )


def _get_prompt() -> str:
    label = "latest" if settings.DEBUG else "production"
    try:
        prompt = (
            _get_langfuse()
            .get_prompt(
                "license-plate-extraction-batch_v2",
                label=label,
            )
            .prompt
        )
        logging.bind(
            label=label,
            prompt_length=len(prompt),
        ).info("Fetched Langfuse QC prompt")
        return prompt
    except Exception as e:  # noqa: BLE001
        logging.bind(label=label).warning(
            f"Failed to fetch Langfuse prompt: {e}. Using default.",
        )
        return DEFAULT_PROMPT


def _run_single_image(
    image_url: str,
    image_index: int,
    prompt: str,
    model_name: str,
) -> list[dict]:
    logging.bind(
        image_index=image_index,
        image_url=image_url,
        model_name=model_name,
    ).info("Running Gemini for single image")
    results = GeminiClient(model_name=model_name).generate(
        prompt=prompt,
        image_urls=[image_url],
    )
    for result in results:
        result["image_index"] = image_index
    logging.bind(
        image_index=image_index,
        image_url=image_url,
        model_name=model_name,
        result_count=len(results),
    ).info("Completed Gemini for single image")
    return results


def run_gemini(
    image_urls: list[str],
    model_name: str,
) -> list[dict]:
    """Run Gemini license-plate extraction one image/angle at a time."""
    if not image_urls:
        logging.bind(model_name=model_name).warning(
            "Gemini run requested with no images",
        )
        return []

    prompt = _get_prompt()
    logging.bind(
        model_name=model_name,
        image_count=len(image_urls),
        prompt_length=len(prompt),
    ).info("Gemini batch run started")
    all_results: list[dict] = []
    for index, image_url in enumerate(image_urls):
        try:
            all_results.extend(
                _run_single_image(image_url, index, prompt, model_name),
            )
        except Exception:
            logging.bind(
                image_index=index,
                image_url=image_url,
                model_name=model_name,
            ).exception(
                "Gemini invocation failed",
            )
    logging.bind(
        model_name=model_name,
        image_count=len(image_urls),
        result_count=len(all_results),
    ).info("Gemini batch run completed")
    return all_results
