# CLAUDE.md — billing_ai

## Descripción del Proyecto

Sistema de gestión de facturas y movimientos financieros multi-tenant construido con Django. Permite ingerir documentos via API (con datos OCR externos), revisarlos, aprobarlos o rechazarlos, y exportar reportes en múltiples formatos.

---

## Stack Técnico

- **Backend:** Django 6.0.3 + Django Rest Framework 3.16.1
- **Base de datos:** SQLite (desarrollo) / PostgreSQL (producción, via psycopg2)
- **Frontend:** Templates Django + JS vanilla + CSS base (sin framework JS)
- **Vistas:** Class-Based Views (CCBV) con `LoginRequiredMixin`
- **PDF:** WeasyPrint
- **Excel:** openpyxl
- **Servidor de producción:** Gunicorn + WhiteNoise
- **Testing:** pytest + pytest-django
- **Python:** 3.12

---

## Estructura de Apps

```
billing_ai/        # Configuración principal (settings, urls, wsgi/asgi)
clients/           # CustomUser, Client, Role (modelo de multi-tenancy)
documents/         # Document, Company (core del negocio)
finance/           # FinancialMovement, MovementCategory
api/               # Endpoints DRF para ingesta de documentos y métricas
```

---

## Comandos Útiles

```bash
# Entorno de desarrollo
python manage.py runserver

# Migraciones
python manage.py makemigrations
python manage.py migrate

# Tests (usa --reuse-db por defecto)
pytest
pytest documents/tests/           # solo una app
pytest -k test_nombre              # test específico

# Estáticos (producción)
python manage.py collectstatic --noinput
```

---

## Configuración

- **Settings:** `billing_ai/settings/base.py` (dev) y `billing_ai/settings/production.py` (prod)
- **Variables de entorno:** `.env` en la raíz (ver `python-dotenv`)
- **Usuario personalizado:** `AUTH_USER_MODEL = 'clients.CustomUser'`
- **Idioma:** Español (`es`), zona horaria UTC

---

## Patrones y Convenciones

### Multi-tenancy
Todos los modelos principales tienen FK a `Client`. Las queries siempre deben filtrarse por `client` para evitar fugas de datos entre tenants.

### Managers
`Document` tiene dos managers:
- `objects` — solo documentos activos (no archivados eliminados)
- `all_objects` — todos los documentos

### Capas de la aplicación
- **Models** — lógica de dominio, métodos de negocio en el propio modelo
- **Services** — `DocumentService`, `MetricsService` para operaciones complejas
- **Selectors** — `DocumentSelector` para queries reutilizables y complejas
- **Views (CBV)** — solo orquestación; delegan a services/selectors
- **Forms** — validación de entradas de usuario

### API (DRF)
- Autenticación: `TokenAuthentication` + `SessionAuthentication`
- La ingesta de documentos (`POST /api/v1/documents/ingest/`) recibe archivos + JSON con datos OCR
- Las API keys tienen prefijo `sk_live_` / `sk_test_` y se almacenan hasheadas

### Testing
- Fixtures en `conftest.py` a nivel de proyecto
- Tests en `<app>/tests/` con nombres `test_*.py`
- Usar `--reuse-db` para acelerar (configurado en `pytest.ini`)
- Settings de test: `billing_ai.settings.base`

---

## Seguridad

- `MediaSecurityMiddleware` bloquea traversal de directorios en `/media/`
- Las API keys se hashean con `make_password` antes de guardar
- CSRF activo en todas las vistas web
- Los medios solo se sirven a usuarios autenticados (verificar en vistas de detalle)

---

## Flujo de Documentos

```
Ingesta (API) → pending → [auto-approve si confianza alta]
                        → approved / rejected (manual)
                        → archived
                        → rectified (nueva versión del documento)
```

- `review_level`: `auto`, `manual`, `recommended`, `required`
- `is_current`: solo el documento más reciente de una cadena de rectificaciones es `True`
- `flow`: `in` (ingresos/ventas), `out` (gastos/compras), `unknown`

---

## Exportaciones

- **CSV / Excel / PDF** disponibles en `/documents/export/`
- Preview antes de exportar en `/documents/export/preview/`
- PDF generado con WeasyPrint desde templates HTML

---

## Docker

```bash
docker build -t billing_ai .
docker run -p 8000:8000 billing_ai
```

El `entrypoint.sh` ejecuta: `collectstatic` → `migrate` → `gunicorn`.

---

## Agentes Disponibles

Ver `AGENTS.md` para el agente `django-architect-agent`, especializado en:
- Refactorización y mejoras de arquitectura Django
- Generación de tests unitarios e integración
- Revisión de JS/CSS
- Propuestas iterativas sin ejecutar cambios directamente
