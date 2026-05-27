from dataclasses import dataclass

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from qc.constants.constants import (
    PROCX_S3_ACCESS_KEY,
    PROCX_S3_BUCKET_NAME,
    PROCX_S3_BUCKET_REGION,
    PROCX_S3_SECRET_ACCESS_KEY,
    REACHX_USE_ACCELERATE_ENDPOINT,
)
from qc.constants.enums import PresignedUrlOperationType
from logger import get_logger

logging = get_logger()


@dataclass
class S3Config:
    bucket_name: str = PROCX_S3_BUCKET_NAME
    access_key: str = PROCX_S3_ACCESS_KEY
    secret_access_key: str = PROCX_S3_SECRET_ACCESS_KEY
    bucket_region: str = PROCX_S3_BUCKET_REGION
    presigned_url_expiration_time: int = 3600 * 24
    use_custom_endpoint: bool = False


DEFAULT_S3_CONFIG = S3Config()


class S3Client:
    def __init__(self, config: S3Config = DEFAULT_S3_CONFIG) -> None:
        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=(
                f"https://s3.{self.config.bucket_region}.amazonaws.com"
                if self.config.use_custom_endpoint
                else None
            ),
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_access_key,
            config=Config(
                signature_version="s3v4",
                region_name=config.bucket_region,
                s3=(
                    {"use_accelerate_endpoint": REACHX_USE_ACCELERATE_ENDPOINT}
                    if self.config.bucket_name == PROCX_S3_BUCKET_NAME
                    else {}
                ),
            ),
            region_name=config.bucket_region,
        )
        self.bucket_name = config.bucket_name
        self.link_expiration_time: int = config.presigned_url_expiration_time

    def get_presigned_urls(
        self,
        file_names: list[str],
        operation: str,
        extra_params: dict | None = None,
    ) -> list[dict] | None:
        presigned_urls = []
        for file in file_names:
            try:
                params = {"Bucket": self.bucket_name, "Key": file}
                if extra_params:
                    params.update(extra_params)
                url = self.client.generate_presigned_url(
                    (
                        "put_object"
                        if operation == PresignedUrlOperationType.PUT.value
                        else "get_object"
                    ),
                    Params=params,
                    ExpiresIn=self.link_expiration_time,
                )
                presigned_urls.append({"file_name": file, "url": url})
            except Exception as e:
                logging.error(f"Error generating presigned URL: {e}")
        return presigned_urls

    def does_file_exist(self, file_path: str) -> bool:
        try:
            self.client.head_object(
                Bucket=self.bucket_name,
                Key=file_path,
            )
            return True
        except ClientError as e:
            logging.info(f"Unexpected error checking file existence: {e}")
            return False

    def upload_file_obj(
        self,
        file_obj: bytes,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> bool:
        try:
            self.client.put_object(
                Bucket=self.config.bucket_name,
                Key=key,
                Body=file_obj,
                ContentType=content_type,
            )
        except ClientError as e:
            logging.error(f"Failed to upload file to S3: {key}, Error: {e}")
            return False
        else:
            logging.info(f"Successfully uploaded file to S3: {key}")
            return True

    def download_file(self, key: str, file_name: str) -> bool:
        try:
            self.client.download_file(self.bucket_name, key, file_name)
        except ClientError as e:
            logging.error(
                f"Failed to download file from S3: {key}, Error: {e}",
            )
            return False
        else:
            logging.info(f"Successfully downloaded file {file_name=}")
            return True
