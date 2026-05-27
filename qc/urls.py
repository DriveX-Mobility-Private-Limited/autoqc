from django.urls import path

from qc.views.health import HealthCheckView
from qc.views.vehicle_analysis import (
    VehicleAnalysisView,
    VehicleAnalysisResultsView,
)
from qc.views.ai_qc_inventory import (
    AIQCInventoryListView,
    AIQCInventoryDetailView,
    AIQCInventoryTaskResultView,
    AIQCInventoryRotateImagesView,
)
from qc.views.listing_qc import ListingQCView

urlpatterns = [
    # Health
    path("health/", HealthCheckView.as_view(), name="health"),
    # Sell-flow vehicle analysis
    path(
        "api/vehicle-analysis/",
        VehicleAnalysisView.as_view(),
        name="vehicle-analysis",
    ),
    path(
        "api/vehicle-analysis/results/<int:transaction_id>/",
        VehicleAnalysisResultsView.as_view(),
        name="vehicle-analysis-results",
    ),
    path(
        "api/vehicle-analysis/task-result/",
        AIQCInventoryTaskResultView.as_view(),
        name="vehicle-analysis-task-result",
    ),
    # Listing QC (triggered by galaxy)
    path(
        "api/listing-qc/",
        ListingQCView.as_view(),
        name="listing-qc",
    ),
    # Boulevard dashboard
    path(
        "api/ai-qc-inventory/",
        AIQCInventoryListView.as_view(),
        name="ai-qc-inventory-list",
    ),
    path(
        "api/ai-qc-inventory/<int:inventory_id>/",
        AIQCInventoryDetailView.as_view(),
        name="ai-qc-inventory-detail",
    ),
    path(
        "api/ai-qc-inventory/task-result/",
        AIQCInventoryTaskResultView.as_view(),
        name="ai-qc-inventory-task-result",
    ),
    path(
        "api/ai-qc-inventory/rotate-images/",
        AIQCInventoryRotateImagesView.as_view(),
        name="ai-qc-inventory-rotate",
    ),
]
