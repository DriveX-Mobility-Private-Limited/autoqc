from pathlib import Path

from environs import Env

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
env = Env()
env.read_env(str(BASE_DIR / ".env"))

ENVIRONMENT = env("ENVIRONMENT", default="development")

# Gemini model configuration
AUTO_QC_GEMINI_MODEL_NAME = env(
    "AUTO_QC_GEMINI_MODEL_NAME",
    default="gemini-2.5-flash",
)
AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME = env(
    "AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME",
    default="gemini-3.1-flash-image",
)

PROCX_S3_BUCKET_NAME = env("PROCX_S3_BUCKET_NAME", default="")
PROCX_S3_BUCKET_PATH = env("PROCX_S3_BUCKET_PATH", default="")
PROCX_S3_BUCKET_REGION = env("PROCX_S3_BUCKET_REGION", default="")
PROCX_S3_ACCESS_KEY = env("PROCX_S3_ACCESS_KEY", default="")
PROCX_S3_SECRET_ACCESS_KEY = env("PROCX_S3_SECRET_ACCESS_KEY", default="")
