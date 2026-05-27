from rest_framework import status
from rest_framework.request import Request
from rest_framework.views import APIView

from qc.responses import StandardResponse
from qc.serializers import ListingQCRequestSerializer
from logger import get_logger

logging = get_logger()


class ListingQCView(APIView):
    """
    Endpoint called by galaxy to trigger QC for a new C2C listing.
    Galaxy sends c2c_inventory_id + callback_url.
    AutoQC fetches data from galaxy, processes, and posts result back.
    """

    def post(self, request: Request) -> StandardResponse:
        try:
            serializer = ListingQCRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            c2c_inventory_id = validated_data["c2c_inventory_id"]
            callback_url = validated_data["callback_url"]

            from qc.tasks.listing_qc import listing_qc_task

            task = listing_qc_task.delay(
                c2c_inventory_id=c2c_inventory_id,
                callback_url=callback_url,
            )

            return StandardResponse(
                data={
                    "task_id": task.id,
                    "c2c_inventory_id": c2c_inventory_id,
                    "status": "PROCESSING",
                    "message": "Listing QC started",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logging.exception("Error triggering listing QC")
            return StandardResponse(
                data={
                    "error": "Failed to trigger listing QC",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
