from rest_framework import serializers


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


class ImageCleanupSerializer(serializers.Serializer):
    image_url = serializers.URLField(required=True)
