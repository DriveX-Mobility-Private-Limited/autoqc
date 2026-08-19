import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from google import genai
from google.genai import types

from qc.clients.gemini_models import BatchLicensePlateResponse
from qc.constants.constants import GOOGLE_AGENT_PLATFORM_MODEL
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
        self.agent_platform_model_name = GOOGLE_AGENT_PLATFORM_MODEL
        self.google_cloud_project = (
            settings.GOOGLE_CLOUD_PROJECT
            or settings.GOOGLE_SERVICE_ACCOUNT_PROJECT_ID
        )
        self.google_cloud_location = settings.GOOGLE_CLOUD_LOCATION
        self.timeout = 120
        self.client = None
        self.agent_platform_client = None

    def _client(self) -> genai.Client:
        return self._enterprise_client()

    def _enterprise_client(self) -> genai.Client:
        if not self.google_cloud_project:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT or GOOGLE_SERVICE_ACCOUNT_PROJECT_ID is "
                "required for Gemini Enterprise service account auth",
            )

        if self.agent_platform_client is None:
            credentials = self._service_account_credentials()
            self.agent_platform_client = genai.Client(
                enterprise=True,
                credentials=credentials,
                project=self.google_cloud_project,
                location=self.google_cloud_location,
            )
        return self.agent_platform_client

    @staticmethod
    def _service_account_credentials() -> Any | None:
        if not (
            settings.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY
            and settings.GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL
        ):
            return None

        from google.oauth2 import service_account

        private_key = settings.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY.replace(
            "\\n",
            "\n",
        )
        service_account_info = {
            "type": settings.GOOGLE_SERVICE_ACCOUNT_TYPE,
            "project_id": (
                settings.GOOGLE_SERVICE_ACCOUNT_PROJECT_ID
                or settings.GOOGLE_CLOUD_PROJECT
            ),
            "private_key_id": settings.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID,
            "private_key": private_key,
            "client_email": settings.GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL,
            "client_id": settings.GOOGLE_SERVICE_ACCOUNT_CLIENT_ID,
            "auth_uri": settings.GOOGLE_SERVICE_ACCOUNT_AUTH_URI,
            "token_uri": settings.GOOGLE_SERVICE_ACCOUNT_TOKEN_URI,
            "auth_provider_x509_cert_url": (
                settings.GOOGLE_SERVICE_ACCOUNT_AUTH_PROVIDER_X509_CERT_URL
            ),
            "client_x509_cert_url": (
                settings.GOOGLE_SERVICE_ACCOUNT_CLIENT_X509_CERT_URL
            ),
            "universe_domain": settings.GOOGLE_SERVICE_ACCOUNT_UNIVERSE_DOMAIN,
        }
        return service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

    def generate(
        self,
        prompt: str,
        image_urls: list[str],
    ) -> list[dict]:
        try:
            return self._generate_with_client(
                client=self._enterprise_client(),
                model_name=self.agent_platform_model_name,
                prompt=prompt,
                image_urls=image_urls,
                source="Agent Platform",
            )
        except Exception:
            logging.exception("Agent Platform Gemini generation failed")
            return []

    def _generate_with_client(
        self,
        client: genai.Client,
        model_name: str,
        prompt: str,
        image_urls: list[str],
        source: str,
    ) -> list[dict]:
        logging.bind(
            model=model_name,
            source=source,
            image_count=len(image_urls),
            prompt_length=len(prompt),
        ).info("Gemini generation request started")
        response = client.models.generate_content(
            model=model_name,
            contents=self._build_contents(prompt, image_urls, upload_client=client),
            config=types.GenerateContentConfig(
                temperature=0,
                top_p=1,
                top_k=40,
                max_output_tokens=32768,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(
                    include_thoughts=False,
                    thinking_budget=8192,
                ),
            ),
        )
        token_usage = self._get_token_usage(response, model_name=model_name)
        logging.info(f"Gemini token usage: {token_usage}")
        results = self._parse_response(response.text, image_urls, token_usage)
        logging.bind(
            model=model_name,
            source=source,
            image_count=len(image_urls),
            result_count=len(results),
            token_usage=token_usage,
        ).info("Gemini generation request completed")
        return results

    def generate_audio_analytics(
        self,
        prompt: str,
        audio_file_path: str,
        mime_type: str,
        response_schema: dict[str, Any] | type | None = None,
    ) -> str | None:
        try:
            logging.bind(
                model=self.agent_platform_model_name,
                file_path=audio_file_path,
                mime_type=mime_type,
                project=self.google_cloud_project,
                location=self.google_cloud_location,
            ).info("Agent Platform audio analytics request started")
            response = self._enterprise_client().models.generate_content(
                model=self.agent_platform_model_name,
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=Path(audio_file_path).read_bytes(),
                        mime_type=mime_type,
                    ),
                ],
                config=self._json_config(response_schema=response_schema),
            )
            logging.bind(
                model=self.agent_platform_model_name,
                token_usage=self._get_token_usage(
                    response,
                    model_name=self.agent_platform_model_name,
                ),
            ).info("Agent Platform audio analytics request completed")
            return response.text
        except Exception:
            logging.bind(
                model=self.agent_platform_model_name,
                file_path=audio_file_path,
                mime_type=mime_type,
                project=self.google_cloud_project,
                location=self.google_cloud_location,
            ).exception("Agent Platform audio analytics request failed")
            return None

    def _build_contents(
        self,
        prompt: str,
        image_urls: list[str],
        upload_client: genai.Client | None = None,
    ) -> list:
        contents = [prompt]
        upload_client = upload_client or self._client()
        for url in image_urls:
            image = self._download_image(url)
            try:
                logging.bind(
                    image_url=url,
                    file_path=image.file_path,
                    size_bytes=image.size_bytes,
                    mime_type=image.mime_type,
                    inline=image.size_bytes <= INLINE_IMAGE_SIZE_LIMIT_BYTES,
                ).info("Gemini image downloaded")
                if image.size_bytes <= INLINE_IMAGE_SIZE_LIMIT_BYTES:
                    contents.append(
                        types.Part.from_bytes(
                            data=Path(image.file_path).read_bytes(),
                            mime_type=image.mime_type,
                        ),
                    )
                else:
                    raise ValueError(
                        "Image exceeds inline Gemini Enterprise limit; "
                        "service account upload support is not configured",
                    )
            finally:
                self._delete_file(image.file_path)
        return contents

    def _download_image(self, url: str) -> DownloadedImage:
        mime_type = self._guess_mime_type(url)
        suffix = Path(url.split("?")[0]).suffix or ".jpg"

        logging.bind(image_url=url, timeout=self.timeout).info(
            "Downloading image",
        )
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

        downloaded = DownloadedImage(
            file_path=temp_file.name,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )
        logging.bind(
            image_url=url,
            file_path=downloaded.file_path,
            size_bytes=downloaded.size_bytes,
            mime_type=downloaded.mime_type,
        ).info("Image downloaded")
        return downloaded

    def _parse_response(
        self,
        response_text: str | None,
        image_urls: list[str],
        token_usage: dict | None = None,
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
            if token_usage:
                result_dict["token_usage"] = token_usage
            results.append(result_dict)
        logging.bind(
            parsed_result_count=len(results),
            image_count=len(image_urls),
        ).info("Gemini JSON response parsed")
        return results

    def _get_token_usage(self, response, model_name: str | None = None) -> dict:
        model_name = model_name or self.model_name
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return {"model": model_name}

        usage_data = {}
        if hasattr(usage, "model_dump"):
            usage_data = usage.model_dump(exclude_none=True)
        elif isinstance(usage, dict):
            usage_data = {
                key: value for key, value in usage.items() if value is not None
            }
        else:
            for field in (
                "prompt_token_count",
                "candidates_token_count",
                "total_token_count",
                "cached_content_token_count",
                "thoughts_token_count",
            ):
                value = getattr(usage, field, None)
                if value is not None:
                    usage_data[field] = value

        usage_data["model"] = model_name
        return usage_data

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

    @classmethod
    def _json_config(
        cls,
        response_schema: dict[str, Any] | type | None = None,
    ) -> types.GenerateContentConfig:
        config: dict[str, Any] = {
            "temperature": 0,
            "response_mime_type": "application/json",
        }
        if response_schema:
            config["response_schema"] = cls._gemini_response_schema(response_schema)
        return types.GenerateContentConfig(**config)

    @classmethod
    def _gemini_response_schema(
        cls,
        response_schema: dict[str, Any] | type,
    ) -> dict[str, Any] | type:
        if not isinstance(response_schema, dict):
            return response_schema
        return cls._strip_unsupported_schema_keys(
            cls._resolve_schema_refs(response_schema, response_schema.get("$defs", {})),
        )

    @classmethod
    def _resolve_schema_refs(cls, value: Any, definitions: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                definition_name = ref.rsplit("/", 1)[-1]
                definition = definitions.get(definition_name, {})
                return cls._resolve_schema_refs(definition, definitions)
            return {
                key: cls._resolve_schema_refs(item, definitions)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._resolve_schema_refs(item, definitions) for item in value]
        return value

    @classmethod
    def _strip_unsupported_schema_keys(cls, value: Any) -> Any:
        unsupported_keys = {
            "$defs",
            "$id",
            "$schema",
            "additionalProperties",
            "allOf",
            "anyOf",
            "default",
            "examples",
            "oneOf",
            "title",
        }
        if isinstance(value, dict):
            return {
                key: cls._strip_unsupported_schema_keys(item)
                for key, item in value.items()
                if key not in unsupported_keys
            }
        if isinstance(value, list):
            return [cls._strip_unsupported_schema_keys(item) for item in value]
        return value

    @staticmethod
    def _delete_file(file_path: str) -> None:
        try:
            os.unlink(file_path)
        except OSError:
            logging.warning(f"Failed to delete temporary image file: {file_path}")
