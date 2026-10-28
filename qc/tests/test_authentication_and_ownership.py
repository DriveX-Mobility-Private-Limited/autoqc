from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from qc.services.resource_ownership_service import (
    ResourceOwnershipError,
    ResourceOwnershipService,
)

SERVICE_KEYS = {
    "galaxy": {"key": "galaxy-secret", "scopes": ("vehicle-analysis",)},
    "boulevard": {"key": "boulevard-secret", "scopes": ("boulevard",)},
}


@override_settings(AUTOQC_SERVICE_API_KEYS=SERVICE_KEYS)
class ServiceAuthenticationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_business_endpoint_rejects_missing_api_key(self) -> None:
        response = self.client.post(
            "/boulevard/api/qc-test/",
            {"image_url": "https://images.example.com/car.jpg"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_business_endpoint_rejects_invalid_api_key(self) -> None:
        response = self.client.post(
            "/boulevard/api/qc-test/",
            {"image_url": "https://images.example.com/car.jpg"},
            format="json",
            HTTP_X_API_KEY="wrong",
        )

        self.assertEqual(response.status_code, 401)

    def test_business_endpoint_rejects_key_without_required_scope(self) -> None:
        response = self.client.post(
            "/boulevard/api/qc-test/",
            {"image_url": "https://images.example.com/car.jpg"},
            format="json",
            HTTP_X_API_KEY="galaxy-secret",
        )

        self.assertEqual(response.status_code, 403)

    @patch("qc.views.vehicle_analysis.run_gemini", return_value=[])
    def test_business_endpoint_accepts_key_with_required_scope(self, _run) -> None:
        response = self.client.post(
            "/boulevard/api/qc-test/",
            {"image_url": "https://images.example.com/car.jpg"},
            format="json",
            HTTP_X_API_KEY="boulevard-secret",
        )

        self.assertEqual(response.status_code, 200)

    @patch(
        "qc.views.vehicle_analysis.ResourceOwnershipService.assert_owner",
        side_effect=ResourceOwnershipError("task is not owned"),
    )
    def test_task_polling_rejects_task_owned_by_another_service(self, _owner) -> None:
        response = self.client.post(
            "/boulevard/api/vehicle-analysis/task-result/",
            {"task_id": "opaque-task-id"},
            format="json",
            HTTP_X_API_KEY="boulevard-secret",
        )

        self.assertEqual(response.status_code, 403)

    @patch(
        "qc.services.cleanup_target_service.PROCX_S3_BUCKET_PATH",
        "self_inspection/",
    )
    @patch("qc.services.cleanup_target_service.PROCX_S3_BUCKET_NAME", "images-bucket")
    def test_cleanup_rejects_unowned_source_before_queueing(self) -> None:
        response = self.client.post(
            "/boulevard/api/image-cleanup/",
            {"image_url": "https://attacker.example/self_inspection/car.jpg"},
            format="json",
            HTTP_X_API_KEY="boulevard-secret",
        )

        self.assertEqual(response.status_code, 400)


class ResourceOwnershipServiceTests(SimpleTestCase):
    @patch("qc.services.resource_ownership_service.get_redis_connection")
    def test_claim_uses_atomic_set_with_expiry(self, get_connection) -> None:
        redis = Mock()
        redis.set.return_value = True
        get_connection.return_value = redis

        ResourceOwnershipService().claim("task", "task-1", "boulevard")

        redis.set.assert_called_once_with(
            "autoqc:resource-owner:task:task-1",
            "boulevard",
            nx=True,
            ex=ResourceOwnershipService.TASK_EXPIRY_SECONDS,
        )

    @patch("qc.services.resource_ownership_service.get_redis_connection")
    def test_unknown_resource_is_not_accessible(self, get_connection) -> None:
        redis = Mock()
        redis.get.return_value = None
        get_connection.return_value = redis

        with self.assertRaises(ResourceOwnershipError):
            ResourceOwnershipService().assert_owner(
                "transaction",
                "transaction-1",
                "galaxy",
            )
