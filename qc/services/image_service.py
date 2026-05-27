import base64
import tempfile
import time
from io import BytesIO
from urllib.parse import urlparse

import pillow_avif  # noqa: F401
import requests
from PIL import Image
from pillow_heif import register_heif_opener

from qc.clients.s3_client import S3Client
from qc.constants.constants import EXCEL_FILES_PREFIX
from qc.constants.constants import IMAGE_PATH_PREFIX
from qc.constants.constants import IMAGEKIT_PRIVATE_KEY
from logger import get_logger

logging = get_logger()


class ImageService:
    def __init__(self):
        register_heif_opener()
        self.s3_client = S3Client()

    def rotate_and_upload(self, image_url: str, rotation_angle: int) -> bool:
        if not self.s3_client.does_file_exist(self._extract_s3_key(image_url)):
            return False

        image = self.download_image(image_url)
        if not image:
            return False

        rotated = self._rotate_image(image, int(rotation_angle))
        s3_key = self._upload_image_to_s3(rotated, image_url)

        return bool(s3_key)

    def _rotate_image(
        self,
        image: Image.Image,
        rotation_angle: int,
    ) -> Image.Image:
        if rotation_angle not in [90, 180, 270]:
            return image
        rotated_image = image.rotate(-rotation_angle, expand=True)
        logging.info(
            f"Rotated image {rotation_angle} degrees clockwise",
        )
        return rotated_image

    def download_image(self, url: str) -> Image.Image | None:
        s3_key = self._extract_s3_key(url)
        logging.info(f"Downloading image from {s3_key}")
        ext = s3_key.split(".")[-1] or "jpg"

        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=True) as tmp:
            if not self.s3_client.download_file(s3_key, tmp.name):
                return None

            image = Image.open(tmp.name)
            image.load()

        logging.info(
            f"Downloaded image from {url}, mode: {image.mode}, "
            f"format: {image.format}",
        )
        return image

    def _upload_image_to_s3(
        self,
        image: Image.Image,
        original_url: str,
    ) -> str | None:
        format_ = image.format or "JPEG"

        if format_.upper() == "JPEG" and image.mode != "RGB":
            original_mode = image.mode
            image = image.convert("RGB")
            logging.info(
                f"Converted image from {original_mode} to RGB "
                f"for JPEG compatibility",
            )

        buffer = BytesIO()
        image.save(buffer, format=format_, optimize=True, quality=100)
        buffer.seek(0)

        s3_key = self._extract_s3_key(original_url)

        if self.s3_client.upload_file_obj(
            buffer.getvalue(),
            s3_key,
            f"image/{format_.lower()}",
        ):
            logging.info(f"Uploaded rotated image to S3: {s3_key}")
            return s3_key

        logging.error(f"Failed to upload rotated image: {s3_key}")
        return None

    def _extract_s3_key(self, image_path: str) -> str:
        if not image_path:
            return ""

        parsed = urlparse(image_path)
        if parsed.scheme and parsed.netloc:
            return parsed.path.lstrip("/")

        for original_prefix, extra in [
            (IMAGE_PATH_PREFIX, EXCEL_FILES_PREFIX),
        ]:
            prefix = original_prefix.rstrip("/") + "/"
            if image_path.startswith(prefix):
                key = image_path[len(prefix):]
                return f"{extra}{key}" if extra else key

        return image_path

    def purge_image_cache(self, image_url: str) -> bool:
        base_url = "https://api.imagekit.io/v1/files"
        purge_url = f"{base_url}/purge"
        headers = {
            "Accept": "application/json",
            "Authorization": self._get_auth_headers(),
            "Content-Type": "application/json",
        }
        data = {"url": image_url}

        response = requests.post(
            purge_url, headers=headers, json=data, timeout=120,
        )
        request_id = response.json().get("requestId")

        poll_url = f"{base_url}/purge/{request_id}"
        poll_headers = {
            "Accept": "application/json",
            "Authorization": self._get_auth_headers(),
        }

        max_retries = 12
        retry_count = 0
        while retry_count < max_retries:
            poll_response = requests.get(
                poll_url,
                headers=poll_headers,
                timeout=120,
            )
            purge_status = poll_response.json().get("status")

            if purge_status == "Completed":
                return True

            time.sleep(5)
            retry_count += 1
        return False

    def _get_auth_headers(self) -> str:
        encoded_private_key = base64.b64encode(
            f"{IMAGEKIT_PRIVATE_KEY}:".encode(),
        ).decode("utf-8")
        return f"Basic {encoded_private_key}"
