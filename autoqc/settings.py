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

CORS_ALLOW_ALL_ORIGINS = True
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
GOOGLE_GEMINI_API_KEY = env.str("GOOGLE_GEMINI_API_KEY", default="")

# Langfuse
LANGFUSE_HOST = env.str("LANGFUSE_HOST", default="")
LANGFUSE_PUBLIC_KEY = env.str("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_SECRET_KEY = env.str("LANGFUSE_SECRET_KEY", default="")

# Internationalization
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True
