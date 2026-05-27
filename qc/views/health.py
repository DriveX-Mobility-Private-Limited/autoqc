from django.http import JsonResponse
from django_redis import get_redis_connection
from rest_framework.views import APIView


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        checks = {"redis": False, "status": "unhealthy"}
        try:
            redis = get_redis_connection("default")
            redis.ping()
            checks["redis"] = True
            checks["status"] = "healthy"
        except Exception as e:
            checks["error"] = str(e)

        status_code = 200 if checks["status"] == "healthy" else 503
        return JsonResponse(checks, status=status_code)
