from corsheaders.defaults import default_headers
from environs import Env

env = Env()
env.read_env()

# Security
SECRET_KEY = env.str("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "corsheaders",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "qc",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
]

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=True)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS: tuple[str, ...] = (
    "GET",
    "POST",
    "PATCH",
    "OPTIONS",
    "DELETE",
    "PUT",
)
CORS_ALLOW_HEADERS: list[str] = [
    *list(default_headers),
    "Content-Type",
    "Rid",
    "St-Auth-Mode",
    "Dnt",
    "Fdi-Version",
    "x-api-key",
]

ROOT_URLCONF = "autoqc.urls"
WSGI_APPLICATION = "autoqc.wsgi.application"

# Database
DATABASES = {}

# Cache
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env.str("REDIS_URL", default="redis://localhost:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Celery
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True

# Gemini
GOOGLE_AGENT_PLATFORM_ENABLED = env.bool(
    "GOOGLE_AGENT_PLATFORM_ENABLED",
    default=True,
)
GOOGLE_CLOUD_PROJECT = env.str("GOOGLE_CLOUD_PROJECT", default="")
GOOGLE_CLOUD_LOCATION = env.str("GOOGLE_CLOUD_LOCATION", default="global")
GOOGLE_SERVICE_ACCOUNT_TYPE = env.str(
    "GOOGLE_SERVICE_ACCOUNT_TYPE",
    default="service_account",
)
GOOGLE_SERVICE_ACCOUNT_PROJECT_ID = env.str(
    "GOOGLE_SERVICE_ACCOUNT_PROJECT_ID",
    default="",
)
GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID = env.str(
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID",
    default="",
)
GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY = env.str(
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY",
    default="",
)
GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL = env.str(
    "GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL",
    default="",
)
GOOGLE_SERVICE_ACCOUNT_CLIENT_ID = env.str(
    "GOOGLE_SERVICE_ACCOUNT_CLIENT_ID",
    default="",
)
GOOGLE_SERVICE_ACCOUNT_AUTH_URI = env.str(
    "GOOGLE_SERVICE_ACCOUNT_AUTH_URI",
    default="https://accounts.google.com/o/oauth2/auth",
)
GOOGLE_SERVICE_ACCOUNT_TOKEN_URI = env.str(
    "GOOGLE_SERVICE_ACCOUNT_TOKEN_URI",
    default="https://oauth2.googleapis.com/token",
)
GOOGLE_SERVICE_ACCOUNT_AUTH_PROVIDER_X509_CERT_URL = env.str(
    "GOOGLE_SERVICE_ACCOUNT_AUTH_PROVIDER_X509_CERT_URL",
    default="https://www.googleapis.com/oauth2/v1/certs",
)
GOOGLE_SERVICE_ACCOUNT_CLIENT_X509_CERT_URL = env.str(
    "GOOGLE_SERVICE_ACCOUNT_CLIENT_X509_CERT_URL",
    default="",
)
GOOGLE_SERVICE_ACCOUNT_UNIVERSE_DOMAIN = env.str(
    "GOOGLE_SERVICE_ACCOUNT_UNIVERSE_DOMAIN",
    default="googleapis.com",
)

# Langfuse
LANGFUSE_HOST = env.str("LANGFUSE_HOST", default="")
LANGFUSE_PUBLIC_KEY = env.str("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_SECRET_KEY = env.str("LANGFUSE_SECRET_KEY", default="")

# Internationalization
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True
