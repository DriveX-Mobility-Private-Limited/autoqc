from datetime import timedelta

from django_redis import get_redis_connection


class ResourceOwnershipError(PermissionError):
    pass


class ResourceOwnershipService:
    """Bind opaque API resource identifiers to their creating service."""

    KEY_PREFIX = "autoqc:resource-owner"
    DEFAULT_EXPIRY_SECONDS = int(timedelta(days=30).total_seconds())
    TASK_EXPIRY_SECONDS = int(timedelta(days=1).total_seconds())

    def __init__(self):
        self.redis = get_redis_connection("default")

    def claim(self, resource_type: str, resource_id: str, service_id: str) -> None:
        key = self._key(resource_type, resource_id)
        expiry = (
            self.TASK_EXPIRY_SECONDS
            if resource_type == "task"
            else self.DEFAULT_EXPIRY_SECONDS
        )
        if self.redis.set(key, service_id, nx=True, ex=expiry):
            return
        self.assert_owner(resource_type, resource_id, service_id)

    def assert_owner(
        self,
        resource_type: str,
        resource_id: str,
        service_id: str,
    ) -> None:
        owner = self.redis.get(self._key(resource_type, resource_id))
        if isinstance(owner, bytes):
            owner = owner.decode()
        if not owner or owner != service_id:
            raise ResourceOwnershipError(
                f"{resource_type} is not owned by the authenticated service",
            )

    def _key(self, resource_type: str, resource_id: str) -> str:
        return f"{self.KEY_PREFIX}:{resource_type}:{resource_id}"
