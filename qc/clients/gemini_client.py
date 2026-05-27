import requests
from django.conf import settings

from qc.clients.gemini_models import BatchLicensePlateResponse
from logger import get_logger

logging = get_logger()

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

MIME_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".heif": "image/heif",
    ".heic": "image/heif",
    ".avif": "image/avif",
}

VALID_VIEW_LABELS = {"front", "rear", "left", "right", "odometer", "other"}


class GeminiClient:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.api_key = settings.GOOGLE_GEMINI_API_KEY
        self.timeout = 120

    def _url(self) -> str:
        return (
            f"{GEMINI_API_BASE}/models/{self.model_name}:generateContent"
            f"?key={self.api_key}"
        )

    def generate(
        self,
        prompt: str,
        image_urls: list[str],
        expected_make_model: str | None = None,
    ) -> list[dict]:
        body = self._build_body(prompt, image_urls, expected_make_model)
        try:
            response = requests.post(
                self._url(), json=body, timeout=self.timeout,
            )
            response.raise_for_status()
            return self._parse_response(response.json(), image_urls)
        except Exception:
            logging.exception("Gemini API call failed")
            return []

    def _build_body(
        self,
        prompt: str,
        image_urls: list[str],
        expected_make_model: str | None = None,
    ) -> dict:
        if expected_make_model:
            prompt = (
                f"{prompt}\n\n"
                f"Expected Vehicle Make/Model: {expected_make_model}\n"
                "Please verify if the visible vehicle matches "
                "this expected make/model."
            )

        parts = [{"text": prompt}]
        for url in image_urls:
            parts.append({
                "file_data": {
                    "file_uri": url,
                    "mime_type": self._guess_mime_type(url),
                },
            })

        return {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.8,
                "topK": 40,
                "maxOutputTokens": 32768,
                "responseMimeType": "application/json",
            },
        }

    def _parse_response(
        self,
        response_json: dict,
        image_urls: list[str],
    ) -> list[dict]:
        text = self._extract_text(response_json)
        if not text:
            return []

        try:
            parsed = BatchLicensePlateResponse.model_validate_json(text)
        except Exception:
            logging.exception("Failed to parse Gemini response")
            return []

        results = []
        for result in parsed.results:
            result_dict = result.model_dump()
            if result.image_index < len(image_urls):
                result_dict["image_url"] = image_urls[result.image_index]
            result_dict["view_label"] = self._normalize_view_label(
                result.view_label,
            )
            results.append(result_dict)
        return results

    @staticmethod
    def _extract_text(response_json: dict) -> str | None:
        try:
            return (
                response_json["candidates"][0]["content"]["parts"][0]["text"]
            )
        except (KeyError, IndexError):
            logging.exception("Empty or malformed Gemini response")
            return None

    @staticmethod
    def _guess_mime_type(url: str) -> str:
        path = url.lower().split("?")[0]
        for ext, mime in MIME_TYPES.items():
            if path.endswith(ext):
                return mime
        return "image/jpeg"

    @staticmethod
    def _normalize_view_label(view_label: str) -> str:
        normalized = view_label.lower().strip()
        if normalized in VALID_VIEW_LABELS:
            return normalized
        logging.warning(
            f"Invalid view label '{view_label}', defaulting to 'other'",
        )
        return "other"
