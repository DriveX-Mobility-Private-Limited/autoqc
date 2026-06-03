from django.urls import path

from qc.views.health import HealthCheckView
from qc.views.vehicle_analysis import VehicleAnalysisResultsView
from qc.views.vehicle_analysis import VehicleAnalysisTaskResultView
from qc.views.vehicle_analysis import VehicleAnalysisView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("api/health/", HealthCheckView.as_view(), name="api-health"),
    path(
        "backstage/api/vehicle-analysis/",
        VehicleAnalysisView.as_view(),
        name="vehicle-analysis",
    ),
    path(
        "backstage/api/vehicle-analysis/task-result/",
        VehicleAnalysisTaskResultView.as_view(),
        name="vehicle-analysis-task-result",
    ),
    path(
        "backstage/api/vehicle-analysis/results/<str:transaction_id>/",
        VehicleAnalysisResultsView.as_view(),
        name="vehicle-analysis-results",
    ),
]
