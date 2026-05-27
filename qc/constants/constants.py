from environs import Env

env = Env()

ENVIRONMENT = env("ENVIRONMENT", default="development")

# Gemini model configuration
AUTO_QC_GEMINI_MODEL_NAME = env(
    "AUTO_QC_GEMINI_MODEL_NAME",
    default="gemini-3-pro-preview",
)
SELL_FLOW_GEMINI_MODEL_NAME = env(
    "SELL_FLOW_GEMINI_MODEL_NAME",
    default="gemini-2.5-pro",
)

# S3 configuration
PROCX_S3_BUCKET_NAME = env("PROCX_S3_BUCKET_NAME", default="")
PROCX_S3_BUCKET_REGION = env("PROCX_S3_BUCKET_REGION", default="ap-south-1")
PROCX_S3_ACCESS_KEY = env("PROCX_S3_ACCESS_KEY", default="")
PROCX_S3_SECRET_ACCESS_KEY = env("PROCX_S3_SECRET_ACCESS_KEY", default="")
REACHX_USE_ACCELERATE_ENDPOINT = (
    env("REACHX_USE_ACCELERATE_ENDPOINT", default="True") == "True"
)

# ImageKit
IMAGE_PATH_PREFIX = "https://ik.imagekit.io/drivex/"
EXCEL_FILES_PREFIX = "Excel_files/"
IMAGEKIT_PRIVATE_KEY = env("IMAGEKIT_PRIVATE_KEY", default="")

# QC thresholds
CONFIDENCE_THRESHOLD = 90.0
THRESHOLD = 2

# EV ineligible fuel types
C2C_INELIGIBLE_FUEL_TYPE = [
    "pure ev",
    "electric(bov)",
    "electric(bov)",
    "pure ev",
    "electric(bov",
    "electric",
]
