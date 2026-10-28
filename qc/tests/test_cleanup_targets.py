from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from qc.clients.s3_client import S3Client
from qc.services.cleanup_target_service import build_cleanup_image_key
from qc.tasks.listing_qc import upload_cleanup_image


class CleanupTargetTests(SimpleTestCase):
    @patch("qc.services.cleanup_target_service.uuid4")
    @patch(
        "qc.services.cleanup_target_service.PROCX_S3_BUCKET_PATH",
        "self_inspection/",
    )
    @patch("qc.services.cleanup_target_service.PROCX_S3_BUCKET_NAME", "images-bucket")
    def test_cleanup_key_is_unique_and_inside_owned_prefix(self, uuid4) -> None:
        uuid4.return_value.hex = "unique"

        key = build_cleanup_image_key(
            "https://images-bucket.s3.ap-south-1.amazonaws.com/"
            "self_inspection/vehicle/front.jpg?signature=secret",
        )

        self.assertEqual(
            key,
            "self_inspection/cleanup/vehicle/front_cleanup_unique.jpg",
        )

    @patch(
        "qc.services.cleanup_target_service.PROCX_S3_BUCKET_PATH",
        "self_inspection/",
    )
    @patch("qc.services.cleanup_target_service.PROCX_S3_BUCKET_NAME", "images-bucket")
    def test_cleanup_rejects_untrusted_host(self) -> None:
        with self.assertRaisesRegex(ValueError, "configured S3 bucket"):
            build_cleanup_image_key("https://attacker.example/self_inspection/car.jpg")

    @patch(
        "qc.services.cleanup_target_service.PROCX_S3_BUCKET_PATH",
        "self_inspection/",
    )
    @patch("qc.services.cleanup_target_service.PROCX_S3_BUCKET_NAME", "images-bucket")
    def test_cleanup_rejects_object_outside_owned_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "service-owned prefix"):
            build_cleanup_image_key(
                "https://images-bucket.s3.amazonaws.com/other/car.jpg",
            )

    @patch("qc.tasks.listing_qc.build_cleanup_image_key", return_value="owned/key")
    @patch("qc.tasks.listing_qc.build_cleanup_image_url", return_value="signed-url")
    @patch("qc.tasks.listing_qc.S3Client")
    def test_cleanup_upload_uses_conditional_write(
        self,
        s3_client,
        _build_url,
        _build_key,
    ) -> None:
        client = Mock()
        client.upload_bytes.return_value = True
        s3_client.return_value = client

        result = upload_cleanup_image(
            "https://images.example/car.jpg",
            {"data_url": "data:image/png;base64,YWJj", "mime_type": "image/png"},
        )

        client.upload_bytes.assert_called_once_with(
            file_key="owned/key",
            data=b"abc",
            content_type="image/png",
            overwrite=False,
        )
        self.assertEqual(result["cleaned_image_path"], "owned/key")

    def test_s3_client_uses_if_none_match_for_non_overwrite_upload(self) -> None:
        s3 = S3Client.__new__(S3Client)
        s3.bucket_name = "images-bucket"
        s3.client = Mock()

        uploaded = s3.upload_bytes(
            "owned/key",
            b"abc",
            "image/png",
            overwrite=False,
        )

        self.assertTrue(uploaded)
        s3.client.put_object.assert_called_once_with(
            Bucket="images-bucket",
            Key="owned/key",
            Body=b"abc",
            ContentType="image/png",
            IfNoneMatch="*",
        )
