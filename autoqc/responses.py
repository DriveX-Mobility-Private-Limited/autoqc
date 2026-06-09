from typing import Any

from rest_framework import status as status_code
from rest_framework.response import Response

JsonDict = dict[str, Any]


class StandardResponseMessages:
    status_mapping = {
        200: "Request successful",
        201: "Resource created successfully",
        204: "Resource deleted successfully",
        400: "Bad request",
        404: "Resource not found",
        500: "Internal server error",
    }


class StandardResponse(Response):
    def __init__(
        self,
        data: JsonDict | None = None,
        status: int = status_code.HTTP_200_OK,
        message: str | None = None,
        **kwargs,
    ):
        formatted_data = {
            "data": data,
            "status": "OK" if status < status_code.HTTP_400_BAD_REQUEST else "error",
            "message": message
            or StandardResponseMessages.status_mapping.get(status, None),
        }
        super().__init__(data=formatted_data, status=status, **kwargs)
