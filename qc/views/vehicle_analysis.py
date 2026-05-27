from rest_framework import status
from rest_framework.request import Request
from rest_framework.views import APIView

from qc.responses import StandardResponse
from qc.serializers import VehicleAnalysisRequestSerializer
from qc.services.redis_service import VehicleAnalysisRedisService
from logger import get_logger

logging = get_logger()


class VehicleAnalysisView(APIView):
    """Trigger vehicle analysis for a single image."""

    def post(self, request: Request) -> StandardResponse:
        try:
            serializer = VehicleAnalysisRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            vehicle_id = validated_data["vehicle_id"]
            image_path = validated_data["image_path"]
            transaction_id = validated_data["transaction_id"]
            angle = validated_data["angle"]

            from qc.tasks.vehicle_analysis_qc import vehicle_analysis_qc_task

            task = vehicle_analysis_qc_task.delay(
                vehicle_id=vehicle_id,
                image_path=image_path,
                transaction_id=transaction_id,
                angle=angle,
            )

            response_data = {
                "task_id": task.id,
                "vehicle_id": vehicle_id,
                "image_path": image_path,
                "transaction_id": transaction_id,
                "angle": angle,
                "status": "PROCESSING",
                "message": "Vehicle analysis started",
            }

            return StandardResponse(
                data=response_data,
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logging.exception("Error triggering vehicle analysis")
            return StandardResponse(
                data={
                    "error": "Failed to trigger analysis",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VehicleAnalysisResultsView(APIView):
    """Retrieve vehicle analysis results by transaction_id from Redis."""

    def get(self, request: Request, transaction_id: int) -> StandardResponse:
        try:
            if not transaction_id:
                return StandardResponse(
                    data={
                        "error": "Missing required parameter",
                        "details": "transaction_id is required",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            redis_service = VehicleAnalysisRedisService()
            angle_results = redis_service.get_all_results(transaction_id)

            if not angle_results:
                return StandardResponse(
                    data={
                        "transaction_id": transaction_id,
                        "results": [],
                        "message": "No results found for this transaction_id",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            results_list = list(angle_results.values())

            response_data = {
                "transaction_id": transaction_id,
                "results": results_list,
                "total_angles": len(results_list),
                "message": "Results retrieved successfully",
            }

            return StandardResponse(
                data=response_data,
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logging.error(f"Error retrieving vehicle analysis results: {e}")
            return StandardResponse(
                data={
                    "error": "Failed to retrieve results",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
