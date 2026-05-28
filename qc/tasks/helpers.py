from concurrent.futures import ThreadPoolExecutor, as_completed

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


def _run_batch(
    batch_urls: list[str],
    batch_offset: int,
    prompt: str,
    model_name: str,
) -> list[dict]:
    results = GeminiClient(model_name=model_name).generate(
        prompt=prompt,
        image_urls=batch_urls,
    )
    for result in results:
        result["image_index"] += batch_offset
    return results


def run_gemini(
    image_urls: list[str],
    model_name: str,
) -> list[dict]:
    """Run Gemini license-plate extraction; batches if image count exceeds limit."""
    if not image_urls:
        return []

    prompt = _get_prompt()
    batch_size = settings.GEMINI_BATCH_SIZE

    if len(image_urls) <= batch_size:
        try:
            return _run_batch(image_urls, 0, prompt, model_name)
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
                _run_batch, urls, offset, prompt, model_name,
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
