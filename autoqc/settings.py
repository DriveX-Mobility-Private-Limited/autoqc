from environs import Env

env = Env()
env.read_env()

# Security
SECRET_KEY = env.str("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Application definition
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "qc",
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
CELERY_BROKER_URL = env.str(
    "CELERY_BROKER_URL", default="redis://localhost:6379/1"
)
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

# Gemini
GOOGLE_GEMINI_API_KEY = env.str("GOOGLE_GEMINI_API_KEY", default="")
AUTOQC_API_KEY = env.str("AUTOQC_API_KEY", default="")

# Langfuse
LANGFUSE_HOST = env.str("LANGFUSE_HOST", default="")
LANGFUSE_PUBLIC_KEY = env.str("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_SECRET_KEY = env.str("LANGFUSE_SECRET_KEY", default="")

# Internationalization
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True
