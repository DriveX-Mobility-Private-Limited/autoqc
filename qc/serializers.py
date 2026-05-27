from rest_framework import serializers

from qc.constants.enums import C2CQCStatus


class VehicleAnalysisRequestSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    image_path = serializers.CharField()
    transaction_id = serializers.CharField()
    angle = serializers.CharField()


class TaskResultRequestSerializer(serializers.Serializer):
    task_id = serializers.CharField()


class RotateImagesSerializer(serializers.Serializer):
    image_url = serializers.CharField()
    rotation_angle = serializers.IntegerField()


class InventoryListRequestSerializer(serializers.Serializer):
    qc_status = serializers.CharField(required=False, allow_blank=True, default="")
    page = serializers.IntegerField(required=False, default=1)


class InventoryProcessRequestSerializer(serializers.Serializer):
    c2c_inventory_id = serializers.IntegerField(required=False)
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        default=[],
    )
    expected_make_model = serializers.CharField(required=False, default="")
    registration_number = serializers.CharField(required=False, default="")


class ListingQCRequestSerializer(serializers.Serializer):
    c2c_inventory_id = serializers.IntegerField()
    callback_url = serializers.URLField()
