import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings
from google import genai
from google.genai import types

from qc.clients.gemini_models import BatchLicensePlateResponse
from logger import get_logger

logging = get_logger()

INLINE_IMAGE_SIZE_LIMIT_BYTES = 15 * 1024 * 1024

MIME_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".heif": "image/heif",
    ".heic": "image/heif",
    ".avif": "image/avif",
}

VALID_VIEW_LABELS = {"front", "rear", "left", "right", "odometer", "other"}


@dataclass
class DownloadedImage:
    file_path: str
    size_bytes: int
    mime_type: str


class GeminiClient:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.api_key = settings.GOOGLE_GEMINI_API_KEY
        self.timeout = 120
        self.client = None

    def _client(self) -> genai.Client:
        if self.client is None:
            self.client = genai.Client(api_key=self.api_key)
        return self.client

    def generate(
        self,
        prompt: str,
        image_urls: list[str],
    ) -> list[dict]:
        try:
            response = self._client().models.generate_content(
                model=self.model_name,
                contents=self._build_contents(prompt, image_urls),
                config=types.GenerateContentConfig(
                    temperature=0,
                    top_p=1,
                    top_k=40,
                    max_output_tokens=32768,
                    response_mime_type="application/json",
                ),
            )
            return self._parse_response(response.text, image_urls)
        except Exception:
            logging.exception("Gemini API call failed")
            return []

    def _build_contents(
        self,
        prompt: str,
        image_urls: list[str],
    ) -> list:
        contents = [prompt]
        for url in image_urls:
            image = self._download_image(url)
            try:
                if image.size_bytes <= INLINE_IMAGE_SIZE_LIMIT_BYTES:
                    contents.append(
                        types.Part.from_bytes(
                            data=Path(image.file_path).read_bytes(),
                            mime_type=image.mime_type,
                        ),
                    )
                else:
                    contents.append(self._client().files.upload(file=image.file_path))
            finally:
                self._delete_file(image.file_path)
        return contents

    def _download_image(self, url: str) -> DownloadedImage:
        mime_type = self._guess_mime_type(url)
        suffix = Path(url.split("?")[0]).suffix or ".jpg"

        with requests.get(
            url,
            stream=True,
            timeout=self.timeout,
            headers={"Accept": "image/*", "Accept-Encoding": "identity"},
        ) as response:
            response.raise_for_status()
            header_content_type = response.headers.get("Content-Type")
            if header_content_type:
                header_mime_type = header_content_type.split(";")[0].strip()
                if header_mime_type.startswith("image/"):
                    mime_type = header_mime_type

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                size_bytes = 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    size_bytes += len(chunk)
                    temp_file.write(chunk)

        return DownloadedImage(
            file_path=temp_file.name,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )

    def _parse_response(
        self,
        response_text: str | None,
        image_urls: list[str],
    ) -> list[dict]:
        if not response_text:
            return []

        try:
            parsed = BatchLicensePlateResponse.model_validate_json(response_text)
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

    @staticmethod
    def _delete_file(file_path: str) -> None:
        try:
            os.unlink(file_path)
        except OSError:
            logging.warning(f"Failed to delete temporary image file: {file_path}")
