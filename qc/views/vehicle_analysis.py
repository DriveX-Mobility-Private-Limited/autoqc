from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from autoqc.celery_app import app as celery_app
from autoqc.responses import StandardResponse
from qc.clients.nano_banana_client import NanoBananaClient
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.serializers import BoulevardQCRerunSerializer
from qc.serializers import ImageCleanupSerializer
from qc.serializers import QCImageTestSerializer
from qc.serializers import VehicleAnalysisRequestSerializer
from qc.serializers import VehicleAnalysisTaskResultSerializer
from qc.services.vehicle_analysis_redis_service import (
    VehicleAnalysisRedisService,
)
from qc.tasks.helpers import run_gemini
from qc.tasks.listing_qc import process_listing_qc
from qc.tasks.listing_qc import vehicle_analysis_qc
from logger import get_logger

logging = get_logger()


class VehicleAnalysisView(APIView):
    """API to trigger vehicle analysis for a single image/angle."""

    def post(self, request: Request) -> Response:
        try:
            serializer = VehicleAnalysisRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            vehicle_id = validated_data["vehicle_id"]
            image_path = validated_data.get("image_path") or ""
            image_url = validated_data.get("image_url") or ""
            transaction_id = validated_data["transaction_id"]
            angle = validated_data["angle"]

            logging.bind(
                vehicle_id=vehicle_id,
                transaction_id=transaction_id,
                angle=angle,
                has_image_path=bool(image_path),
                has_image_url=bool(image_url),
            ).info("Vehicle analysis request accepted")
            task = vehicle_analysis_qc.delay(
                vehicle_id=vehicle_id,
                image_path=image_path,
                image_url=image_url,
                transaction_id=transaction_id,
                angle=angle,
            )

            response_data = {
                "task_id": task.id,
                "vehicle_id": vehicle_id,
                "image_path": image_path,
                "image_url": image_url,
                "transaction_id": transaction_id,
                "angle": angle,
                "status": "PROCESSING",
                "message": "Vehicle analysis started",
            }

            logging.bind(
                task_id=task.id,
                vehicle_id=vehicle_id,
                transaction_id=transaction_id,
                angle=angle,
            ).info("Vehicle analysis task queued")
            return StandardResponse(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            logging.exception("Error triggering vehicle analysis")
            return StandardResponse(
                {
                    "error": "Failed to trigger analysis",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VehicleAnalysisResultsView(APIView):
    """API to retrieve vehicle analysis results by transaction_id."""

    def get(self, request: Request, transaction_id: str) -> Response:
        try:
            if not transaction_id:
                return StandardResponse(
                    {
                        "error": "Missing required parameter",
                        "details": "transaction_id is required in the path",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            angle_results = VehicleAnalysisRedisService().get_all_results(
                transaction_id,
            )
            logging.bind(
                transaction_id=transaction_id,
                result_count=len(angle_results),
            ).info("Vehicle analysis results lookup completed")
            if not angle_results:
                return StandardResponse(
                    {
                        "transaction_id": transaction_id,
                        "results": [],
                        "message": "No results found for this transaction_id",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            results_list = list(angle_results.values())
            return StandardResponse(
                {
                    "transaction_id": transaction_id,
                    "results": results_list,
                    "total_angles": len(results_list),
                    "message": "Results retrieved successfully",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logging.exception("Error retrieving vehicle analysis results")
            return StandardResponse(
                {
                    "error": "Failed to retrieve results",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VehicleAnalysisTaskResultView(APIView):
    """Poll Celery task state/result for a vehicle analysis task."""

    def post(self, request: Request) -> Response:
        serializer = VehicleAnalysisTaskResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task_id = serializer.validated_data["task_id"]

        task_result = celery_app.AsyncResult(task_id)
        logging.bind(
            task_id=task_id,
            state=task_result.state,
            ready=task_result.ready(),
        ).info("Vehicle analysis task result polled")
        response_data = {
            "task_id": task_id,
            "status": task_result.state,
            "message": f"Task is in {task_result.state} state",
        }
        if task_result.ready():
            response_data["result"] = task_result.result

        return StandardResponse(response_data, status=status.HTTP_200_OK)


class QCImageTestView(APIView):
    """Run QC synchronously for one arbitrary image URL."""

    def post(self, request: Request) -> Response:
        try:
            serializer = QCImageTestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            image_url = serializer.validated_data["image_url"]
            angle = serializer.validated_data["angle"]

            logging.bind(
                image_url=image_url,
                angle=angle,
            ).info("Boulevard QC test started")
            raw_ai_response = run_gemini(
                image_urls=[image_url],
                model_name=AUTO_QC_GEMINI_MODEL_NAME,
            )
            logging.bind(
                image_url=image_url,
                angle=angle,
                result_count=len(raw_ai_response),
            ).info("Boulevard QC test completed")
            return Response(
                {
                    "success": bool(raw_ai_response),
                    "image_url": image_url,
                    "angle": angle,
                    "raw_ai_response": raw_ai_response,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logging.exception("Error running QC image test")
            return Response(
                {
                    "success": False,
                    "error": "Failed to run QC image test",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BoulevardQCRerunView(APIView):
    """Retrigger listing QC asynchronously for Boulevard."""

    def post(self, request: Request) -> Response:
        serializer = BoulevardQCRerunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        c2c_inventory_id = serializer.validated_data["c2c_inventory_id"]
        image_urls = serializer.validated_data["image_urls"]

        try:
            logging.bind(
                c2c_inventory_id=c2c_inventory_id,
                image_count=len(image_urls),
            ).info("Boulevard QC rerun requested")
            task = process_listing_qc.delay(
                c2c_inventory_id=c2c_inventory_id,
                image_urls=image_urls,
            )
            logging.bind(
                task_id=task.id,
                c2c_inventory_id=c2c_inventory_id,
                image_count=len(image_urls),
            ).info("Boulevard QC rerun task queued")

            return StandardResponse(
                {
                    "task_id": task.id,
                    "c2c_inventory_id": c2c_inventory_id,
                    "image_count": len(image_urls),
                    "status": "PROCESSING",
                    "message": "Listing QC rerun started",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception as e:
            logging.exception("Error rerunning Boulevard QC")
            return StandardResponse(
                {
                    "error": "Failed to rerun QC",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ImageCleanupView(APIView):
    """Remove humans/clutter from a vehicle inspection image."""

    def post(self, request: Request) -> Response:
        try:
            serializer = ImageCleanupSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            image_url = serializer.validated_data["image_url"]
            target_angle = serializer.validated_data["target_angle"]

            logging.bind(
                image_url=image_url,
                target_angle=target_angle,
            ).info("Boulevard image cleanup requested")
            cleanup_result = NanoBananaClient().cleanup_image(
                image_url=image_url,
                target_angle=target_angle,
            )
            if not cleanup_result:
                return StandardResponse(
                    {
                        "error": "Failed to clean up image",
                        "image_url": image_url,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            logging.bind(
                image_url=image_url,
                target_angle=target_angle,
                skipped=cleanup_result.get("skipped"),
                model=cleanup_result.get("model"),
                has_final_orientation_analysis=bool(
                    cleanup_result.get("final_orientation_analysis"),
                ),
            ).info("Boulevard image cleanup completed")
            return StandardResponse(
                {
                    "image_url": image_url,
                    "target_angle": target_angle,
                    **cleanup_result,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logging.exception("Error cleaning up image")
            return StandardResponse(
                {
                    "error": "Failed to clean up image",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
