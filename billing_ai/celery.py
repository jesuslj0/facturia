import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "billing_ai.settings.base")

app = Celery("billing_ai")
# Todas las claves CELERY_* de settings.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
