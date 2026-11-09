from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load dotenv
import os
from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('1', 'true', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip()]

INTERNAL_IPS = [
    "127.0.0.1",
]

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'debug_toolbar',
    'rest_framework',
    'rest_framework.authtoken',
    'api',
    'clients',
    'documents',
    'finance.apps.FinanceConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',
]

ROOT_URLCONF = 'billing_ai.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'billing_ai.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'es'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK  = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# --- Archivos subidos (privados) ---------------------------------------------
# Los archivos NUNCA se sirven desde una URL pública: se entregan mediante vistas
# autenticadas que comprueban el tenant (ver documents.views.DocumentFileView).
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")

_use_r2 = os.getenv("USE_R2_STORAGE", "True").lower() in ("1", "true", "yes") and all(
    [R2_BUCKET_NAME, R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]
)

if _use_r2:
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": R2_BUCKET_NAME,
            "endpoint_url": R2_ENDPOINT_URL,
            "access_key": R2_ACCESS_KEY_ID,
            "secret_key": R2_SECRET_ACCESS_KEY,
            "region_name": "auto",
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 300,
            # Claves por contenido (SHA-256): reescribir la misma clave guarda los mismos bytes.
            "file_overwrite": True,
        },
    }
else:
    # Desarrollo/tests sin credenciales: disco local.
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --- Extracción con Claude --------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "claude-haiku-5-5")
EXTRACTION_FALLBACK_MODEL = os.getenv("EXTRACTION_FALLBACK_MODEL", "claude-sonnet-5-5")
EXTRACTION_EFFORT = os.getenv("EXTRACTION_EFFORT", "low")
EXTRACTION_FALLBACK_EFFORT = os.getenv("EXTRACTION_FALLBACK_EFFORT", "medium")
EXTRACTION_MAX_TOKENS = int(os.getenv("EXTRACTION_MAX_TOKENS", "8192"))
EXTRACTION_TIMEOUT_SECONDS = float(os.getenv("EXTRACTION_TIMEOUT_SECONDS", "120"))
EXTRACTION_MAX_PAGES = int(os.getenv("EXTRACTION_MAX_PAGES", "20"))
EXTRACTION_MAX_IMAGE_SIDE = int(os.getenv("EXTRACTION_MAX_IMAGE_SIDE", "2000"))   # px, lado mayor
EXTRACTION_MAX_IMAGE_MB = int(os.getenv("EXTRACTION_MAX_IMAGE_MB", "5"))          # límite por imagen de la API
EXTRACTION_FALLBACK_CONFIDENCE = float(os.getenv("EXTRACTION_FALLBACK_CONFIDENCE", "0.80"))

# --- Cola de tareas (Celery + Redis) -----------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() in ("1", "true", "yes")
CELERY_TASK_ACKS_LATE = True                  # si el worker muere, la tarea se reentrega
CELERY_WORKER_PREFETCH_MULTIPLIER = 1         # tareas largas: no acaparar
CELERY_TASK_IGNORE_RESULT = True              # el estado vive en la BD (Document/ExtractionRun)
CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_SOFT_TIME_LIMIT = 600
CELERY_TASK_TIME_LIMIT = 660
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}   # > límite de la tarea
EXTRACTION_MAX_RETRIES = int(os.getenv("EXTRACTION_MAX_RETRIES", "5"))
EXTRACTION_RETRY_BASE_SECONDS = int(os.getenv("EXTRACTION_RETRY_BASE_SECONDS", "30"))
EXTRACTION_RETRY_MAX_SECONDS = int(os.getenv("EXTRACTION_RETRY_MAX_SECONDS", "900"))
EXTRACTION_STALE_MINUTES = int(os.getenv("EXTRACTION_STALE_MINUTES", "15"))

# Límites de subida
UPLOAD_MAX_FILE_MB = int(os.getenv("UPLOAD_MAX_FILE_MB", "20"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Logging (sin cabeceras, claves ni datos personales)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_USER_MODEL = "clients.CustomUser"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

X_FRAME_OPTIONS = "SAMEORIGIN"