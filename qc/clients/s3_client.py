from dataclasses import dataclass

import boto3
from botocore.client import Config

from logger import get_logger
from qc.constants.constants import PROCX_S3_ACCESS_KEY
from qc.constants.constants import PROCX_S3_BUCKET_NAME
from qc.constants.constants import PROCX_S3_BUCKET_REGION
from qc.constants.constants import PROCX_S3_SECRET_ACCESS_KEY
from qc.constants.enums import PresignedUrlOperationType

logging = get_logger()


@dataclass
class S3Config:
    bucket_name: str = PROCX_S3_BUCKET_NAME
    access_key: str = PROCX_S3_ACCESS_KEY
    secret_access_key: str = PROCX_S3_SECRET_ACCESS_KEY
    bucket_region: str = PROCX_S3_BUCKET_REGION
    presigned_url_expiration_time: int = 3600


DEFAULT_S3_CONFIG = S3Config()


class S3Client:
    def __init__(self, config: S3Config = DEFAULT_S3_CONFIG) -> None:
        self.config = config
        self.bucket_name = config.bucket_name
        self.link_expiration_time = config.presigned_url_expiration_time
        self.client = None

        credentials = {}
        if config.access_key and config.secret_access_key:
            credentials = {
                "aws_access_key_id": config.access_key,
                "aws_secret_access_key": config.secret_access_key,
            }

        self.client = boto3.client(
            "s3",
            **credentials,
            config=Config(
                signature_version="s3v4",
                region_name=config.bucket_region,
            ),
            region_name=config.bucket_region,
        )

    def generate_presigned_get_url(self, file_key: str) -> str | None:
        return self._generate_presigned_url(
            file_key=file_key,
            operation_type=PresignedUrlOperationType.GET.value,
        )

    def _generate_presigned_url(
        self,
        file_key: str,
        operation_type: str,
    ) -> str | None:
        if not self.client:
            logging.bind(
                file_key=file_key,
                operation_type=operation_type,
            ).error("S3 client unavailable for presigned URL generation")
            return None

        try:
            operation = (
                "put_object"
                if operation_type == PresignedUrlOperationType.PUT.value
                else "get_object"
            )
            logging.bind(
                file_key=file_key,
                operation=operation,
                bucket_name=self.bucket_name,
                expires_in=self.link_expiration_time,
            ).info("Generating S3 presigned URL")
            url = self.client.generate_presigned_url(
                operation,
                Params={"Bucket": self.bucket_name, "Key": file_key},
                ExpiresIn=self.link_expiration_time,
            )
            logging.bind(
                file_key=file_key,
                operation=operation,
                generated=bool(url),
            ).info("Generated S3 presigned URL")
            return url
        except Exception as e:
            logging.bind(
                file_key=file_key,
                operation_type=operation_type,
            ).error(
                f"Failed to generate S3 presigned URL: {e}",
            )
            return None
