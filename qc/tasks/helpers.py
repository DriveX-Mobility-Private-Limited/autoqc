from django.conf import settings
from langfuse import Langfuse

from qc.clients.gemini_client import GeminiClient
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
        return _get_langfuse().get_prompt(
            "license-plate-extraction-batch", label=label,
        ).prompt
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to fetch Langfuse prompt: {e}. Using default.")
        return DEFAULT_PROMPT


def _run_single_image(
    image_url: str,
    image_index: int,
    prompt: str,
    model_name: str,
) -> list[dict]:
    results = GeminiClient(model_name=model_name).generate(
        prompt=prompt,
        image_urls=[image_url],
    )
    for result in results:
        result["image_index"] = image_index
    return results


def run_gemini(
    image_urls: list[str],
    model_name: str,
) -> list[dict]:
    """Run Gemini license-plate extraction one image/angle at a time."""
    if not image_urls:
        return []

    prompt = _get_prompt()
    all_results: list[dict] = []
    for index, image_url in enumerate(image_urls):
        try:
            all_results.extend(
                _run_single_image(image_url, index, prompt, model_name),
            )
        except Exception:
            logging.exception(
                f"Gemini invocation failed for image_index={index}",
            )
    return all_results
