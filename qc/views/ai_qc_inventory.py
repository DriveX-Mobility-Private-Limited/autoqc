from rest_framework import status
from rest_framework.request import Request
from rest_framework.views import APIView

from autoqc.celery_app import app as celery_app
from qc.clients.galaxy_client import GalaxyClient
from qc.constants.enums import C2CQCStatus
from qc.responses import StandardResponse
from qc.serializers import (
    InventoryListRequestSerializer,
    InventoryProcessRequestSerializer,
    RotateImagesSerializer,
    TaskResultRequestSerializer,
)
from logger import get_logger

logging = get_logger()


class AIQCInventoryListView(APIView):
    """Boulevard dashboard: list and process AI QC inventories."""

    def get(self, request: Request):
        try:
            serializer = InventoryListRequestSerializer(data=request.GET)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            qc_status = validated_data["qc_status"]
            page = validated_data["page"]

            galaxy_client = GalaxyClient()
            data = galaxy_client.get_inventory_list(
                qc_status=qc_status,
                page=page,
            )

            if data is None:
                return StandardResponse(
                    data={"error": "Failed to fetch inventory list from galaxy"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            return StandardResponse(data=data, status=status.HTTP_200_OK)

        except Exception as e:
            logging.error(f"Error in AIQCInventoryListView: {e}")
            return StandardResponse(
                data={
                    "error": "An error occurred while loading the inventory list.",
                    "qc_status_choices": C2CQCStatus.values(),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request: Request):
        """Process inventory images with Gemini."""
        try:
            serializer = InventoryProcessRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            c2c_inventory_id = validated_data.get("c2c_inventory_id")

            if c2c_inventory_id:
                galaxy_client = GalaxyClient()
                inventory_data = galaxy_client.get_inventory(c2c_inventory_id)
                if not inventory_data:
                    return StandardResponse(
                        data={"error": "C2C inventory not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                image_urls = inventory_data.get("image_urls", [])
                expected_make_model = inventory_data.get("expected_make_model", "")
                registration_number = inventory_data.get(
                    "registration_number", "",
                )

                if not image_urls:
                    return StandardResponse(
                        data={
                            "error": "No images found for this C2C inventory",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )

                from qc.tasks.helpers import run_gemini_task

                task_result = run_gemini_task.delay(
                    image_urls=image_urls,
                    expected_make_model=expected_make_model,
                    registration_number=registration_number,
                )

                response_data = {
                    "c2c_inventory_id": c2c_inventory_id,
                    "task_id": task_result.id,
                    "vehicle_brand": inventory_data.get("vehicle_brand"),
                    "vehicle_model": inventory_data.get("vehicle_model"),
                    "registration_number": registration_number,
                    "expected_make_model": expected_make_model,
                    "total_images": len(image_urls),
                    "image_urls": image_urls,
                }

                return StandardResponse(
                    data=response_data, status=status.HTTP_200_OK,
                )

            # Direct image URLs provided
            image_urls = validated_data.get("image_urls", [])
            expected_make_model = validated_data.get("expected_make_model", "")
            registration_number = validated_data.get("registration_number", "")

            from qc.tasks.helpers import run_gemini_task

            task_result = run_gemini_task.delay(
                image_urls=image_urls,
                expected_make_model=expected_make_model,
                registration_number=registration_number,
            )

            response_data = {
                "c2c_inventory_id": None,
                "task_id": task_result.id,
                "vehicle_brand": None,
                "vehicle_model": None,
                "registration_number": None,
                "expected_make_model": expected_make_model,
                "total_images": len(image_urls),
                "image_urls": image_urls,
            }

            return StandardResponse(
                data=response_data, status=status.HTTP_200_OK,
            )

        except Exception as e:
            logging.error(f"Error in AIQCInventoryListView POST: {e}")
            return StandardResponse(
                data={
                    "error": "An error occurred while processing the images.",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AIQCInventoryDetailView(APIView):
    """Get inventory detail including raw AI response."""

    def get(self, request: Request, inventory_id: int):
        try:
            galaxy_client = GalaxyClient()
            inventory_data = galaxy_client.get_inventory(inventory_id)
            if not inventory_data:
                return StandardResponse(
                    data={"error": "C2C inventory not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return StandardResponse(
                data=inventory_data, status=status.HTTP_200_OK,
            )

        except Exception as e:
            logging.error(f"Error in AIQCInventoryDetailView GET: {e}")
            return StandardResponse(
                data={
                    "error": "An error occurred while retrieving data.",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AIQCInventoryTaskResultView(APIView):
    """Poll Celery task status by task ID."""

    def post(self, request: Request):
        serializer = TaskResultRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        task_id = validated_data["task_id"]

        task_result = celery_app.AsyncResult(task_id)

        response_data = {
            "task_id": task_id,
            "status": task_result.state,
            "message": f"Task is in {task_result.state} state",
        }

        if task_result.ready():
            response_data["result"] = task_result.result

        return StandardResponse(
            data=response_data,
            status=status.HTTP_200_OK,
        )


class AIQCInventoryRotateImagesView(APIView):
    """Rotate an inspection image and purge CDN cache."""

    def post(self, request: Request):
        serializer = RotateImagesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        image_url = validated_data["image_url"]
        rotation_angle = validated_data["rotation_angle"]

        from qc.tasks.image_rotation import rotate_image_and_clear_cache

        rotate_image_and_clear_cache.delay(image_url, rotation_angle)
        return StandardResponse(
            data={
                "message": "Image rotated, please refresh in sometime",
                "original_url": image_url,
                "rotation_angle": rotation_angle,
            },
            status=status.HTTP_200_OK,
        )
