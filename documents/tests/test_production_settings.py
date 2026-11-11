"""Los ajustes de producción deben poder importarse (antes fallaban siempre con NameError)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_ENV = {
    "PATH": os.environ.get("PATH", ""),
    "DJANGO_SETTINGS_MODULE": "billing_ai.settings.production",
    "SECRET_KEY": "x",
    "POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_HOST": "pg",
}
R2 = {"R2_BUCKET_NAME": "b", "R2_ENDPOINT_URL": "https://x.r2.cloudflarestorage.com",
      "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "s"}
CODE = ("import django; django.setup(); from django.conf import settings; "
        "print(settings.DATABASES['default']['ENGINE'], settings.STORAGES['default']['BACKEND'])")


def run(extra):
    return subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env={**BASE_ENV, **extra},
                          capture_output=True, text=True, timeout=60)


def test_production_settings_import_with_r2_and_postgres():
    r = run(R2)
    assert r.returncode == 0, r.stderr[-500:]
    assert "postgresql" in r.stdout and "S3Storage" in r.stdout


def test_missing_r2_gives_clear_error_not_nameerror():
    r = run({"USE_R2_STORAGE": "False"})
    assert r.returncode != 0
    assert "AssertionError" in r.stderr and "Faltan variables R2_*" in r.stderr and "NameError" not in r.stderr


def test_csrf_origins_follow_allowed_hosts():
    code = "import django; django.setup(); from django.conf import settings; print(settings.CSRF_TRUSTED_ORIGINS)"
    env = {**BASE_ENV, **R2, "ALLOWED_HOSTS": "a.com,.b.com,web.easypanel.host", "CSRF_TRUSTED_ORIGINS": "https://extra.io"}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stdout.strip() == str(["https://a.com", "https://*.b.com", "https://web.easypanel.host", "https://extra.io"])
