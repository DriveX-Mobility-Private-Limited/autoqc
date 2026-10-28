from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
from uuid import uuid4

from qc.constants.constants import (
    PROCX_S3_ALLOWED_IMAGE_HOSTS,
    PROCX_S3_BUCKET_NAME,
    PROCX_S3_BUCKET_PATH,
)


def build_cleanup_image_key(image_url: str) -> str:
    source_key = resolve_owned_cleanup_source_key(image_url)
    prefix = PROCX_S3_BUCKET_PATH.strip("/")
    relative_path = source_key.removeprefix(f"{prefix}/")
    path = PurePosixPath(relative_path)
    suffix = path.suffix
    if suffix:
        cleanup_name = f"{path.stem}_cleanup_{uuid4().hex}{suffix}"
    else:
        cleanup_name = f"{path.name}_cleanup_{uuid4().hex}"
    cleanup_path = path.with_name(cleanup_name)
    return str(PurePosixPath(prefix) / "cleanup" / cleanup_path)


def resolve_owned_cleanup_source_key(image_url: str) -> str:
    parsed_url = urlparse(image_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ValueError("Cleanup source must be an HTTPS URL")

    hostname = parsed_url.hostname.lower().rstrip(".")
    bucket = PROCX_S3_BUCKET_NAME
    raw_path = unquote(parsed_url.path).lstrip("/")
    virtual_hosted = hostname == f"{bucket}.s3.amazonaws.com" or (
        hostname.startswith(f"{bucket}.s3.") and hostname.endswith(".amazonaws.com")
    )
    path_style = hostname.startswith("s3") and hostname.endswith(".amazonaws.com")

    if virtual_hosted:
        source_key = raw_path
    elif path_style and raw_path.startswith(f"{bucket}/"):
        source_key = raw_path.removeprefix(f"{bucket}/")
    elif hostname in {host.lower() for host in PROCX_S3_ALLOWED_IMAGE_HOSTS}:
        source_key = raw_path
    else:
        raise ValueError("Cleanup source is not in the configured S3 bucket")

    raw_parts = source_key.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("Cleanup source object key is invalid")
    prefix = PROCX_S3_BUCKET_PATH.strip("/")
    if not prefix or not source_key.startswith(f"{prefix}/"):
        raise ValueError("Cleanup source is outside the service-owned prefix")
    return source_key
