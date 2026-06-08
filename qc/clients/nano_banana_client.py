import base64
import uuid
from pathlib import Path

from google.genai import types

from logger import get_logger
from qc.clients.s3_client import S3Client
from qc.clients.gemini_client import GeminiClient
from qc.constants.constants import AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME
from qc.constants.constants import PROCX_S3_BUCKET_PATH

logging = get_logger()

CLEANUP_PROMPT = """
Edit this vehicle inspection image.

Remove all people, humans, body parts, bags, personal items, clutter, other
vehicles, and any foreground/background distractions that are not part of the
primary two-wheeler.

Keep the primary two-wheeler exactly the same: shape, color, registration plate,
odometer/details if visible, lighting direction, camera angle, crop,
perspective, shadows, and image resolution. Do not beautify, redraw, replace,
rotate, upscale, or change the vehicle. Fill removed areas naturally using the
surrounding background so the result looks like the same real inspection photo.

Return only the edited image.
""".strip()


class NanoBananaClient(GeminiClient):
    def __init__(self, model_name: str = AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME):
        super().__init__(model_name=model_name)

    def cleanup_image(self, image_url: str) -> dict | None:
        image = None
        try:
            image = self._download_image(image_url)
            response = self._client().models.generate_content(
                model=self.model_name,
                contents=[
                    CLEANUP_PROMPT,
                    types.Part.from_bytes(
                        data=Path(image.file_path).read_bytes(),
                        mime_type=image.mime_type,
                    ),
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            edited_image = self._extract_image(response)
            if not edited_image:
                return None

            token_usage = self._get_token_usage(response)
            logging.info(f"Nano Banana token usage: {token_usage}")
            return {
                **edited_image,
                "success": True,
                "model": self.model_name,
                "token_usage": token_usage,
            }
        except Exception:
            logging.exception("Nano Banana image cleanup failed")
            return None
        finally:
            if image:
                self._delete_file(image.file_path)

    def cleanup_image_to_s3(
        self,
        image_url: str,
        c2c_inventory_id: int | None = None,
        image_index: int | None = None,
    ) -> dict | None:
        cleanup_result = self.cleanup_image(image_url)
        if not cleanup_result:
            return None

        upload_result = self.upload_cleanup_result(
            cleanup_result=cleanup_result,
            c2c_inventory_id=c2c_inventory_id,
            image_index=image_index,
        )
        if not upload_result:
            cleanup_result.pop("data_url", None)
            cleanup_result["upload_status"] = "FAILED"
            return cleanup_result

        cleanup_result.pop("data_url", None)
        return {
            **cleanup_result,
            **upload_result,
            "upload_status": "SUCCESS",
        }

    def upload_cleanup_result(
        self,
        cleanup_result: dict,
        c2c_inventory_id: int | None = None,
        image_index: int | None = None,
    ) -> dict | None:
        data_url = cleanup_result.get("data_url")
        if not data_url:
            return None

        image_bytes, mime_type = self._decode_data_url(data_url)
        file_key = self._build_cleanup_file_key(
            mime_type=mime_type,
            c2c_inventory_id=c2c_inventory_id,
            image_index=image_index,
        )
        s3_client = S3Client()
        if not s3_client.upload_bytes(file_key, image_bytes, mime_type):
            return None

        return {
            "cleaned_image_path": file_key,
            "cleaned_image_url": s3_client.generate_presigned_get_url(file_key),
        }

    def _extract_image(self, response) -> dict | None:
        parts = getattr(response, "parts", None) or []
        if not parts:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(candidates[0].content, "parts", None) or []

        for part in parts:
            inline_data = getattr(part, "inline_data", None) or getattr(
                part,
                "inlineData",
                None,
            )
            if not inline_data:
                continue

            image_bytes = inline_data.data
            if isinstance(image_bytes, str):
                image_base64 = image_bytes
            else:
                image_base64 = base64.b64encode(image_bytes).decode()
            mime_type = inline_data.mime_type or "image/png"
            return {
                "data_url": f"data:{mime_type};base64,{image_base64}",
                "mime_type": mime_type,
            }
        return None

    @staticmethod
    def _decode_data_url(data_url: str) -> tuple[bytes, str]:
        header, encoded_image = data_url.split(",", 1)
        mime_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
        return base64.b64decode(encoded_image), mime_type

    @staticmethod
    def _build_cleanup_file_key(
        mime_type: str,
        c2c_inventory_id: int | None = None,
        image_index: int | None = None,
    ) -> str:
        extension = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/heif": "heif",
        }.get(mime_type, "png")
        inventory_part = c2c_inventory_id or "unknown"
        index_part = image_index if image_index is not None else "unknown"
        base_path = PROCX_S3_BUCKET_PATH.strip("/")
        key = (
            f"autoqc/cleaned-images/{inventory_part}/"
            f"image-{index_part}-{uuid.uuid4().hex}.{extension}"
        )
        if base_path:
            return f"{base_path}/{key}"
        return key
