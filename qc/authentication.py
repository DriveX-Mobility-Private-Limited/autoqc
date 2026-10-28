import secrets
from dataclasses import dataclass

from django.conf import settings
from rest_framework import authentication, exceptions, permissions


@dataclass(frozen=True)
class ServicePrincipal:
    service_id: str
    scopes: frozenset[str]

    @property
    def is_authenticated(self) -> bool:
        return True


class ServiceAPIKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate trusted service callers with the ``x-api-key`` header."""

    header_name = "x-api-key"

    def authenticate(self, request):
        presented_key = request.headers.get(self.header_name, "")
        if not presented_key:
            return None

        matches = []
        for service_id, config in settings.AUTOQC_SERVICE_API_KEYS.items():
            configured_key = config.get("key", "")
            if configured_key and secrets.compare_digest(
                presented_key.encode(),
                configured_key.encode(),
            ):
                matches.append((service_id, config))

        if len(matches) == 1:
            service_id, config = matches[0]
            return (
                ServicePrincipal(
                    service_id=service_id,
                    scopes=frozenset(config.get("scopes", ())),
                ),
                service_id,
            )

        raise exceptions.AuthenticationFailed("Invalid service API key.")

    def authenticate_header(self, request):
        return self.header_name


class ServiceScopePermission(permissions.BasePermission):
    """Require the endpoint's declared service scope."""

    message = "The authenticated service is not allowed to use this endpoint."

    def has_permission(self, request, view):
        required_scopes = getattr(view, "required_service_scopes", ())
        if isinstance(required_scopes, str):
            required_scopes = (required_scopes,)
        if not required_scopes:
            return False
        return bool(set(required_scopes) & set(getattr(request.user, "scopes", ())))


def service_id_for_request(request) -> str:
    return request.user.service_id
