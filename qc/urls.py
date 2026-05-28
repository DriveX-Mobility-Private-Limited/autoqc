from django.urls import path

from qc.views.health import HealthCheckView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
]
