from .base import *
# `import *` no trae los nombres con guion bajo: hay que importarlo explícitamente.
from .base import _use_r2
import os

DEBUG = False
SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "facturia.xyz,www.facturia.xyz").split(",")
    if h.strip()
]

# Seguridad HTTPS (el proxy inverso debe enviar X-Forwarded-Proto)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() in ("1", "true", "yes")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
SECURE_CONTENT_TYPE_NOSNIFF = True

# Sin debug toolbar en producción
INSTALLED_APPS = [a for a in INSTALLED_APPS if a != "debug_toolbar"]
MIDDLEWARE = [m for m in MIDDLEWARE if "debug_toolbar" not in m]

def _origin(host):
    host = host.strip()
    return f"https://*{host}" if host.startswith(".") else f"https://{host}"


# Orígenes de confianza para CSRF: los de ALLOWED_HOSTS (https) más los de CSRF_TRUSTED_ORIGINS (opcional).
CSRF_TRUSTED_ORIGINS = [_origin(h) for h in ALLOWED_HOSTS if h != "*"] + [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
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
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Archivos subidos: ver STORAGES en base.py (Cloudflare R2). En producción
# las credenciales R2_* son obligatorias.
assert _use_r2, "Faltan variables R2_* para el almacenamiento de documentos"
