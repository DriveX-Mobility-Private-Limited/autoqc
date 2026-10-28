import os
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from qc.clients.remote_image_downloader import (
    RemoteImageDownloader,
    RemoteImageDownloadError,
)


class FakeResponse:
    def __init__(self, *, headers=None, chunks=None, redirect=False) -> None:
        self.headers = headers or {}
        self._chunks = chunks or []
        self.is_redirect = redirect
        self.is_permanent_redirect = False
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self._chunks


class RemoteImageDownloaderTests(SimpleTestCase):
    @patch("qc.clients.remote_image_downloader.requests.get")
    @patch("qc.clients.remote_image_downloader.socket.getaddrinfo")
    def test_rejects_private_address_before_connecting(self, getaddrinfo, get) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("127.0.0.1", 80))]

        with self.assertRaisesRegex(RemoteImageDownloadError, "non-public"):
            RemoteImageDownloader().download("http://internal.example/image.jpg")

        get.assert_not_called()

    @patch("qc.clients.remote_image_downloader.requests.get")
    @patch("qc.clients.remote_image_downloader.socket.getaddrinfo")
    def test_revalidates_redirect_target(self, getaddrinfo, get) -> None:
        getaddrinfo.side_effect = [
            [(None, None, None, None, ("93.184.216.34", 443))],
            [(None, None, None, None, ("169.254.169.254", 80))],
        ]
        response = FakeResponse(
            headers={"Location": "http://metadata.example/latest"},
            redirect=True,
        )
        get.return_value = response

        with self.assertRaisesRegex(RemoteImageDownloadError, "non-public"):
            RemoteImageDownloader().download("https://images.example/car.jpg")

        self.assertEqual(get.call_count, 1)
        self.assertTrue(response.closed)

    @patch("qc.clients.remote_image_downloader.requests.get")
    @patch("qc.clients.remote_image_downloader.socket.getaddrinfo")
    def test_rejects_declared_oversize_before_streaming(self, getaddrinfo, get) -> None:
        getaddrinfo.return_value = [
            (None, None, None, None, ("93.184.216.34", 443)),
        ]
        response = FakeResponse(
            headers={
                "Content-Type": "image/jpeg",
                "Content-Length": "11",
            },
        )
        get.return_value = response

        with self.assertRaisesRegex(RemoteImageDownloadError, "size limit"):
            RemoteImageDownloader(max_bytes=10).download(
                "https://images.example/car.jpg",
            )

        self.assertTrue(response.closed)

    @patch("qc.clients.remote_image_downloader.requests.get")
    @patch("qc.clients.remote_image_downloader.socket.getaddrinfo")
    def test_aborts_stream_when_running_size_exceeds_limit(
        self,
        getaddrinfo,
        get,
    ) -> None:
        getaddrinfo.return_value = [
            (None, None, None, None, ("93.184.216.34", 443)),
        ]
        response = FakeResponse(
            headers={"Content-Type": "image/jpeg"},
            chunks=[b"123456", b"78901"],
        )
        get.return_value = response

        with self.assertRaisesRegex(RemoteImageDownloadError, "size limit"):
            RemoteImageDownloader(max_bytes=10).download(
                "https://images.example/car.jpg",
            )

        self.assertTrue(response.closed)

    @patch("qc.clients.remote_image_downloader.requests.get")
    @patch("qc.clients.remote_image_downloader.socket.getaddrinfo")
    def test_downloads_public_image_with_bounded_request(
        self, getaddrinfo, get
    ) -> None:
        getaddrinfo.return_value = [
            (None, None, None, None, ("93.184.216.34", 443)),
        ]
        response = FakeResponse(
            headers={"Content-Type": "image/png", "Content-Length": "3"},
            chunks=[b"abc"],
        )
        get.return_value = response

        downloaded = RemoteImageDownloader(max_bytes=10).download(
            "https://images.example/car.png",
        )
        try:
            self.assertEqual(downloaded.size_bytes, 3)
            self.assertEqual(downloaded.mime_type, "image/png")
            self.assertEqual(Path(downloaded.file_path).read_bytes(), b"abc")
        finally:
            os.unlink(downloaded.file_path)

        get.assert_called_once_with(
            "https://images.example/car.png",
            stream=True,
            timeout=(5, 30),
            allow_redirects=False,
            headers={"Accept": "image/*", "Accept-Encoding": "identity"},
        )
        self.assertTrue(response.closed)
