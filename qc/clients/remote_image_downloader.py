import ipaddress
import os
import socket
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

MAX_IMAGE_DOWNLOAD_BYTES = 15 * 1024 * 1024
MAX_REDIRECTS = 4
DOWNLOAD_TIMEOUT_SECONDS = (5, 30)
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass
class DownloadedImage:
    file_path: str
    size_bytes: int
    mime_type: str


class RemoteImageDownloadError(ValueError):
    pass


class RemoteImageDownloader:
    """Download public HTTP(S) images with SSRF and size protections."""

    def __init__(
        self,
        *,
        max_bytes: int = MAX_IMAGE_DOWNLOAD_BYTES,
        max_redirects: int = MAX_REDIRECTS,
        timeout: tuple[int, int] = DOWNLOAD_TIMEOUT_SECONDS,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.timeout = timeout

    def download(
        self, url: str, default_mime_type: str = "image/jpeg"
    ) -> DownloadedImage:
        current_url = url
        response = None
        for redirect_count in range(self.max_redirects + 1):
            self._validate_public_url(current_url)
            response = requests.get(
                current_url,
                stream=True,
                timeout=self.timeout,
                allow_redirects=False,
                headers={"Accept": "image/*", "Accept-Encoding": "identity"},
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise RemoteImageDownloadError(
                        "Image redirect has no Location header"
                    )
                if redirect_count == self.max_redirects:
                    raise RemoteImageDownloadError("Image URL exceeded redirect limit")
                current_url = urljoin(current_url, location)
                continue
            break

        if response is None:
            raise RemoteImageDownloadError("Image download failed")

        temp_path = ""
        try:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            mime_type = content_type.split(";", 1)[0].strip() or default_mime_type
            if not mime_type.startswith("image/"):
                raise RemoteImageDownloadError("Remote resource is not an image")

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError as error:
                    raise RemoteImageDownloadError(
                        "Remote image has an invalid Content-Length",
                    ) from error
                if declared_size < 0 or declared_size > self.max_bytes:
                    raise RemoteImageDownloadError("Remote image exceeds size limit")

            suffix = Path(urlparse(current_url).path).suffix[:10] or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_path = temp_file.name
                size_bytes = 0
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    size_bytes += len(chunk)
                    if size_bytes > self.max_bytes:
                        raise RemoteImageDownloadError(
                            "Remote image exceeds size limit"
                        )
                    temp_file.write(chunk)

            return DownloadedImage(
                file_path=temp_path,
                size_bytes=size_bytes,
                mime_type=mime_type,
            )
        except Exception:
            if temp_path:
                with suppress(FileNotFoundError):
                    os.unlink(temp_path)
            raise
        finally:
            response.close()

    @staticmethod
    def _validate_public_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise RemoteImageDownloadError("Only HTTP(S) image URLs are allowed")
        if not parsed.hostname or parsed.username or parsed.password:
            raise RemoteImageDownloadError("Image URL host is invalid")

        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except socket.gaierror as error:
            raise RemoteImageDownloadError(
                "Image URL host could not be resolved"
            ) from error

        if not addresses:
            raise RemoteImageDownloadError("Image URL host resolved to no addresses")
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise RemoteImageDownloadError(
                    "Image URL resolves to a non-public address",
                )
