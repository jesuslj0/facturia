"""Settings para desarrollo local con docker-compose.yml (Postgres en contenedor).

El flujo clásico (venv + runserver + SQLite) sigue usando `base.py`.
"""
import os

from .base import *  # noqa: F401,F403

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-solo-para-docker-local")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "billing_ai"),
        "USER": os.environ.get("POSTGRES_USER", "billing_ai"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "billing_ai"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# Dentro de Docker la IP del navegador no es 127.0.0.1, así que INTERNAL_IPS
# no sirve: mostramos la debug toolbar siempre que DEBUG esté activo.
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
}
