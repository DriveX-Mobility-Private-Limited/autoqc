from rest_framework import serializers

VALID_ANGLE_LABELS = {"front", "rear", "left", "right", "odometer", "other"}


class VehicleAnalysisRequestSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField(required=True)
    image_path = serializers.CharField(required=False, allow_blank=True)
    image_url = serializers.URLField(required=False)
    transaction_id = serializers.CharField(required=True)
    angle = serializers.CharField(required=True)

    def validate(self, attrs):
        image_url = attrs.get("image_url")
        image_path = attrs.get("image_path")
        if not image_url and not image_path:
            raise serializers.ValidationError(
                "Either image_url or image_path is required.",
            )
        return attrs


class VehicleAnalysisTaskResultSerializer(serializers.Serializer):
    task_id = serializers.CharField(required=True)


class QCImageTestSerializer(serializers.Serializer):
    image_url = serializers.URLField(required=True)
    angle = serializers.CharField(required=False, allow_blank=True, default="")


class BoulevardQCRerunSerializer(serializers.Serializer):
    c2c_inventory_id = serializers.IntegerField(required=True)
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        allow_empty=False,
        required=True,
    )


class ImageCleanupSerializer(serializers.Serializer):
    image_url = serializers.URLField(required=True)
    target_angle = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_target_angle(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized and normalized not in VALID_ANGLE_LABELS:
            raise serializers.ValidationError(
                "target_angle must be one of front, rear, left, right, "
                "odometer, or other.",
            )
        return normalized
