from .base import *
import os

DEBUG = False
SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = ["facturia.xyz", "www.facturia.xyz"]

CSRF_TRUSTED_ORIGINS = [
    "https://facturia.xyz",
    "https://www.facturia.xyz",
]

# Base de datos PostgreSQL
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# Archivos estáticos
STATIC_ROOT = "/app/staticfiles"
STATIC_URL = "/static/"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Archivos media (opcional)
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
