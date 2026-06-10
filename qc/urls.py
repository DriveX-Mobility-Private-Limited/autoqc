from django.urls import path

from qc.views.vehicle_analysis import BoulevardQCRerunView
from qc.views.vehicle_analysis import ImageCleanupView
from qc.views.health import HealthCheckView
from qc.views.vehicle_analysis import QCImageTestView
from qc.views.vehicle_analysis import VehicleAnalysisResultsView
from qc.views.vehicle_analysis import VehicleAnalysisTaskResultView
from qc.views.vehicle_analysis import VehicleAnalysisView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("api/health/", HealthCheckView.as_view(), name="api-health"),
    path(
        "boulevard/api/image-cleanup/",
        ImageCleanupView.as_view(),
        name="boulevard-image-cleanup",
    ),
    path(
        "boulevard/api/qc-test/",
        QCImageTestView.as_view(),
        name="boulevard-qc-test",
    ),
    path(
        "boulevard/api/rerun-qc/",
        BoulevardQCRerunView.as_view(),
        name="boulevard-rerun-qc",
    ),
    path(
        "api/vehicle-analysis/",
        VehicleAnalysisView.as_view(),
        name="vehicle-analysis",
    ),
    path(
        "api/vehicle-analysis/task-result/",
        VehicleAnalysisTaskResultView.as_view(),
        name="vehicle-analysis-task-result",
    ),
    path(
        "api/vehicle-analysis/results/<str:transaction_id>/",
        VehicleAnalysisResultsView.as_view(),
        name="vehicle-analysis-results",
    ),
]
