# CLAUDE.md — FacturIA (`billing_ai`)

## Qué es

Aplicación multi-tenant de gestión de facturas y movimientos financieros. Cada `Client` (empresa) tiene sus usuarios, terceros, documentos y movimientos. Los documentos (facturas, tickets, presupuestos, albaranes) se **suben desde la app y se leen con OCR/IA (API de Claude)**; una persona los revisa, aprueba, rechaza, archiva o rectifica, y se exportan a CSV/Excel/PDF. Hay métricas por periodo y un panel de inicio.

Convive con el flujo antiguo: **n8n** hacía el OCR fuera y enviaba los datos ya extraídos a `POST /api/v1/documents/ingest/` (sigue activo mientras `N8N_INGEST_ENABLED=True`).

Idioma del producto, comentarios y mensajes: **español** (`LANGUAGE_CODE="es"`, `TIME_ZONE="UTC"`).

## Stack (versiones reales de `requirements.txt`)

- Python 3.12 · Django 6.1.3 · DRF 3.18.3 · vistas basadas en clases (CBV) con `LoginRequiredMixin`
- Frontend: templates Django + JS vanilla + CSS propio (sin frameworks). Font Awesome, Inter y pdf.js 3.9.179 por CDN
- BD: PostgreSQL 16 en desarrollo (Docker) y producción
- OCR: `anthropic` 2.7 + `pydantic` (salida estructurada), `pillow-heif`/`Pillow`/`pypdf` para preprocesar
- Cola: Celery 5.7 + Redis 7
- Archivos: `django-storages` + `boto3` → Cloudflare R2 (UE); Cloudflare R2 Bucket en dev/tests
- Export: `openpyxl` (Excel), WeasyPrint 60.2 (PDF); `babel` para fechas en español
- Despliegue: Gunicorn + WhiteNoise, Docker Compose (también Easypanel)
- Tests: pytest + pytest-django + factory_boy + pytest-cov

## Estructura

```
billing_ai/    settings/{base,production,docker_dev}.py, celery.py, storage.py, listing.py, urls.py
clients/       Client, Role, CustomUser (AUTH_USER_MODEL); ficha de empresa y logo (/clients/)
documents/     Núcleo: modelos, vistas web, servicios, extracción OCR, comandos de gestión
finance/       FinancialMovement, MovementCategory (+ categorías por defecto vía señal al crear Client)
api/           ApiKey, HasApiKey, ingesta n8n, listado de documentos y métricas (DRF)
templates/     base.html, components/, private/{documents,finance,metrics,clients}/, public/auth/
static/        css/ (base, ui, por página), js/ (vanilla, uno por pantalla/componente)
docs/plan-ocr.md   Plan de migración a OCR + registro de decisiones H0–H10 (histórico; ver «Notas»)
.claude/agents/    ui-designer y unit-test-creator (subagentes del proyecto)
```

`documents/` por dentro:

```
models.py            Company, Document, DocumentCategory, Folder, Tag, DocumentFile, ExtractionBatch,
                     ExtractionRun, InvoiceLine, TaxBreakdown, DocumentAuditLog
views.py             CBV: lista, detalle (POST con `action=`), subida, rectificar, export, preview, métricas, inicio
selectors/           DocumentSelector: querysets reutilizables (for_client, filtered, detail_queryset…)
                     drive_selector: árbol virtual de la vista «Archivo» (DrivePath, DriveSelector, TYPE_GROUPS)
filters/             get_filtered_documents / get_exportable_documents (filtros del listado y exports)
forms/               upload (multi-archivo) y rectificación
services/            Lógica de negocio (ver abajo)
services/extraction/ Paquete OCR (ver abajo)
tasks.py             Tarea Celery `documents.process_document`
validators.py        NIF/CIF/NIE (clean_tax_id, check_tax_id) · company_names.py: display_name / name_key
templatetags/ui.py   {% icon %}, {% badge %}, pretty_date: iconos y badges de estado unificados
utils.py             Export CSV/Excel/PDF y normalize_tax (Decimal; neutraliza inyección de fórmulas)
management/commands/ Operación (ver «Comandos»)
```

## Pipeline de extracción (OCR con Claude)

```
Subida (upload.py) ─ valida tamaño + tipo real (firma, no extensión) ─ duplicado por SHA-256 (por tenant)
   └─ crea Document(pending, processing_status=uploaded, flow=unknown, source=upload) + DocumentFile + auditoría
      └─ enqueue_processing (on_commit) → Celery: tasks.process_document
         └─ processing.run_processing: claim_document (UPDATE condicional = idempotencia)
            ├─ preprocess.load_and_preprocess  (PDF tal cual; imágenes: HEIC→JPEG, EXIF, ≤2000 px, ≤5 MB)
            ├─ extraction.run_extraction       (ClaudeExtractor Haiku → fallback Sonnet si procede)
            │     └─ cada intento queda en ExtractionRun (tokens, coste, error, raw_response)
            └─ apply.apply_extraction          (rellena Document, TaxBreakdown, InvoiceLine; valida; audita)
```

- **Estados** (`Document.processing_status`): `uploaded → queued → processing → processed` o `failed`; `batched` para la Batch API. `Document.is_processing` bloquea editar/aprobar/rechazar mientras dura. Un `failed` se puede rellenar a mano o relanzar (`upload.retry_processing`, acción `retry` del detalle).
- **Reintentos**: errores `retryable` (429, timeout, caída) → backoff exponencial con jitter (`EXTRACTION_RETRY_BASE_SECONDS`×2ⁿ, tope `…MAX_SECONDS`, respeta `retry-after`) hasta `EXTRACTION_MAX_RETRIES`; después `failed`. Errores definitivos (archivo dañado, >`EXTRACTION_MAX_PAGES` páginas, petición inválida) → `failed` sin reintentar. Un worker caído se detecta por `processing_started_at` (> `EXTRACTION_STALE_MINUTES`). Si Redis no está disponible el documento vuelve a `uploaded` (lo recoge `enqueue_extraction`).
- **Extractor** (`services/extraction/`): `base.py` (protocolo `Extractor`, errores con `retryable`/`fallback_eligible`), `claude.py` (`messages.parse` con esquema Pydantic; prompt del sistema cacheado), `schemas.py` (salida de Claude), `normalize.py` (texto → `Decimal`/fechas; calcula el **flujo `in`/`out` comparando NIF con el del cliente**, no lo decide el modelo), `prompts.py` (`PROMPT_VERSION`: **súbela al cambiar cualquier texto**), `pricing.py` (coste estimado; Batch = 50 %), `runner.py` (principal + respaldo), `batch.py` (Batch API).
- **Respaldo a Sonnet** solo si: respuesta inválida/rechazo, confianza < `EXTRACTION_FALLBACK_CONFIDENCE` (0,80) o hay una incidencia `model_fixable` (NIF mal leído, descuadre, dato ausente). Duplicados o cliente sin NIF no gastan Sonnet.
- **Validación determinista** (`services/validation.py`): `validate()` → incidencias `ERROR`/`WARNING`/`INFO` guardadas en `Document.validation_issues`; `decide()` fija `review_level`. Total = base + IVA + recargo − retención (`services/taxes.py`, tolerancia 0,02). Incluye dígito de control de NIF/CIF/NIE, fechas plausibles, tipos de IVA/retención habituales, cuadre de líneas, duplicados por emisor + nº (`services/duplicates.py`).
- **Auto-aprobación**: `EXTRACTION_AUTO_APPROVE=False` por defecto. `apply_extraction` **nunca aprueba por sí solo** salvo que esté activada, no haya ERROR ni WARNING y la confianza ≥ `EXTRACTION_AUTO_APPROVE_MIN_CONFIDENCE` (0,90).
- **Terceros** (`services/companies.py`): `get_or_create_company` evita duplicados por NIF canónico (sin `ES`, guiones, etc.) o por `name_key` (sin tildes, puntuación ni forma jurídica). `manage.py merge_companies` fusiona los ya duplicados.
- **Organización** (`services/organization.py`): tipo, tercero, categoría (`DocumentCategory`, distinta de `MovementCategory`), carpeta virtual y etiquetas; todo se resuelve contra el cliente del documento (un id de otro tenant se ignora).
- **Registro**: una línea por documento (`document= client= outcome= tokens cost`), solo ids. `services/usage.py` agrega tokens/coste.
- **Retención/RGPD**: `services/retention.py`, `DOCUMENT_RETENTION_YEARS` (10, provisional); una cadena de rectificaciones se conserva hasta que caducan todas sus versiones.

### Reglas al tocar esto

- Los importes son `Decimal`, **nunca `float`** (el esquema los recibe como texto). Ojo: `DocumentIngestSerializer` (n8n) aún usa `FloatField`.
- No registrar NIF, nombres, cabeceras ni claves en logs; usar ids.
- Los tests nunca usan red ni claves reales: se inyecta `FakeExtractor` (`documents/tests/fakes.py`).
- Una rectificativa **resta siempre** (`services/signs.py`: `signed_amount`/`document_sign`), venga en positivo (n8n) o negativo (IA). Es la única fuente de verdad para métricas y exports.
- El archivo almacenado no se modifica nunca; el preprocesado solo prepara los bytes que van al proveedor.

## Modelo de datos (resumen)

- `Document`: FK `Client`, `Company` (SET_NULL, admite vacío), `category`, `folder`, `tags`. Estado (`pending/approved/rejected`), `review_level` (`auto/manual/recommended/required`), `flow` (`in` venta / `out` compra / `unknown`), `source` (`n8n/upload/import`), `processing_status`, `validation_issues`, `currency`, `iban`. Versionado de rectificaciones: `parent_document`, `version`, `is_current` (único `is_current` por padre). `quarter` es propiedad calculada.
- **Managers**: `Document.objects` excluye archivados; **`Document.all_objects`** los incluye. El pipeline de procesado, `DocumentFileView` y los comandos usan `all_objects`.
- `Document.save()` llama a `full_clean()` siempre (coste y validación): ojo con `update_fields` y cargas masivas.
- `DocumentFile`: SHA-256, MIME, tamaño, páginas, origen; `unique(client, sha256)`. Las rectificaciones reutilizan el archivo del original.
- `ExtractionRun`: un intento de extracción (modelo, `prompt_version`, `is_fallback`, tokens, `cost_usd`, error). `ExtractionBatch`: lote de la Batch API.
- `InvoiceLine` (con `page`), `TaxBreakdown` (`vat/surcharge/withholding`, importes positivos), `DocumentAuditLog` (solo añade; `save()` falla si ya tiene pk).
- `Company`: `tax_id` NULL si vacío (único por cliente), `name_key`, `is_provider`/`is_customer`.

## Archivos y multi-tenancy

- **Todas las queries se filtran por `request.user.client`.** Un acceso a otro tenant debe dar 404. Usa `DocumentSelector.for_client(client)`.
- Los archivos **no tienen URL pública**: se sirven por vistas autenticadas (`DocumentFileView`, `ClientLogoView`, recibo de movimiento) con `billing_ai.storage.private_file_response`.
- Claves de almacenamiento: `<client_id>/<tipo>/AAAA/MM/<sha256><ext>` (`HashedFileField`/`HashedImageField`). Producción **exige** credenciales R2 (`assert _use_r2`).
- `billing_ai/listing.py`: chips de filtros activos, pestañas de estado y paginación compacta para los listados (solo usa `request.GET`).

## API (DRF)

- `POST /api/v1/documents/ingest/` — contrato n8n. Cabecera `X-API-Key: <prefix>.<secret>` (`HasApiKey`; prefijo `sk_live_`/`sk_test_`, secreto hasheado, cliente inactivo rechazado). Archivo repetido → **409**; `N8N_INGEST_ENABLED=False` → **410**. Lógica en `services/ingest.py` (compartida con `import_n8n`).
- `GET /api/v1/documents/` y `GET /api/v1/metrics/dashboard/?start=&end=` — sesión o token, filtrados por el cliente del usuario.

## Comandos

```bash
# Desarrollo: siempre en Docker (Postgres + Redis + web con runserver + worker Celery)
docker compose up --build                        # http://localhost:8000 (settings.docker_dev); migra al arrancar
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py makemigrations   # el código está montado en /app
docker compose build                             # OBLIGATORIO tras tocar requirements.txt (billing_ai/__init__ importa celery)
docker compose restart worker                    # el worker no recarga solo al cambiar código

# Tests (dentro del contenedor, contra Postgres)
docker compose exec web pytest                   # ~775 tests; usa --reuse-db y excluye live_api
docker compose exec web pytest documents/tests/ -k nombre
docker compose exec web pytest -m live_api -s    # API real de Claude: cuesta dinero, requiere ANTHROPIC_API_KEY

# Cola de extracción
docker compose exec web python manage.py enqueue_extraction [--sync] [--client N] [--limit N] [--status uploaded,failed]

# Operación (anteponer `docker compose exec web`)
python manage.py submit_batch [--client N] [--limit N] [--dry-run]   # Batch API (~50 % más barata)
python manage.py collect_batch                   # recoger lotes; idempotente, ejecutar periódicamente
python manage.py extraction_cost [--client N --from F --to F]
python manage.py purge_expired [--apply]         # retención; sin --apply solo simula
python manage.py merge_companies                 # fusiona terceros duplicados
python manage.py backfill_h1 [--dry-run]         # DocumentFile/TaxBreakdown/auditoría de documentos antiguos
python manage.py sync_media_to_storage [--dry-run]   # media/ local → R2
python manage.py import_n8n <carpeta> --client N [--dry-run]
python manage.py n8n_exit_report                 # ¿se puede apagar n8n?
python manage.py collectstatic --noinput
```

## Configuración

- `DJANGO_SETTINGS_MODULE`: `billing_ai.settings.base` (por defecto en `pytest.ini`; define SQLite y solo es la base de las otras dos), `docker_dev` (la que usa el desarrollo diario en Docker; Postgres, debug toolbar) y `production` (HTTPS, Postgres, sin debug toolbar, R2 obligatorio).
- Variables en `.env` (python-dotenv). Plantillas: `.env.prod.example`, `.env.easypanel.example`. Principales: `SECRET_KEY`, `ALLOWED_HOSTS`, `POSTGRES_*`, `R2_*`, `ANTHROPIC_API_KEY`, `CELERY_BROKER_URL`.
- Extracción: `EXTRACTION_MODEL` (claude-haiku-5-5), `EXTRACTION_FALLBACK_MODEL` (claude-sonnet-5-5), `EXTRACTION_EFFORT`, `EXTRACTION_MAX_TOKENS`, `EXTRACTION_MAX_PAGES` (20), `EXTRACTION_MAX_IMAGE_SIDE/MB`, `EXTRACTION_AUTO_APPROVE*`, `UPLOAD_MAX_FILE_MB` (20), `CELERY_TASK_ALWAYS_EAGER` (tests/depuración).
- Despliegue: `docker-compose.yml` (dev), `docker-compose.prod.yml` (Postgres propio), `docker-compose.easypanel.yml` (Postgres de Easypanel; web + redis + worker). `entrypoint.sh` ejecuta `collectstatic` + `migrate` y arranca Gunicorn; el worker sustituye el `command`.

## Frontend

- **Sistema visual nuevo** (login, detalle, subida, inicio, métricas): tokens y degradado `--grad-surface` en `static/css/base.css`; componentes compartidos en `static/css/ui.css` (`.btn` + `-primary/-success/-danger/-warning/-info/-neutral/-ghost/-sm`, `.badge-status` con `.tone-*`, `.chip`, `.table`, `.dialog`). Las hojas de página **no** redefinen esos componentes. Tema oscuro; sin `!important` ni estilos en línea salvo valores dinámicos del backend.
- Badges e iconos: `{% load ui %}` → `{% badge 'review' value %}`, `{% icon name %}`.
- JS vanilla en `static/js/`, uno por componente: `document-viewer.js` (pdf.js, detalle y rectificar), `document-detail.js` (enfocar campo de una incidencia), `tax-calculator.js`, `edit-toggle.js`, `confirm-modal.js`, `auto-refresh.js` (`data-autorefresh="seg"` mientras hay documentos en proceso), `upload.js` (arrastrar/soltar, «Hacer foto» con `capture`), `list-page.js`, `chart-kit.js` (gráficos de inicio/métricas), `home.js`, `metrics.js`, formularios de finanzas.
- **PDF (WeasyPrint)**: `invoice_pdf.html` e `invoice_list_pdf.html` usan CSS propio/en línea y solo propiedades compatibles con WeasyPrint; no mezclar con los estilos de pantalla.
- El detalle del documento se maneja con un único POST con `action=` (`approve/reject/save/archive/unarchive/rectify/retry`); las funciones `approve_document`, `reject_document`… de `views.py` son auxiliares, **no** vistas.

## Testing

- `conftest.py` (raíz): fixtures `client_entity`, `other_client_entity`, `user`, `other_user`, `company`, `document`, `approved_document`, `api_key`, `auth_client`, `api_client`, `movement_category`, `financial_movement`… y dos autouse: almacenamiento en `tmp_path` (nunca R2 ni `media/`) y desconexión de la señal de categorías por defecto.
- `documents/tests/factories.py` (factory_boy) y `documents/tests/fakes.py` (`make_result`, `FakeExtractor`).
- Tests por app en `<app>/tests/test_*.py`. Siempre probar el aislamiento entre tenants (cliente A no ve ni edita datos de B → 404/queryset filtrado).
- Cubrir también casos límite: sin importes, sin tercero, consulta vacía, archivo repetido, error reintentable vs definitivo.

## Cómo trabajar aquí

- Cambios pequeños, claros y minimalistas; sin sobreingeniería. Vistas finas: la lógica va en `services/` o `selectors/`, no en la vista ni en el template.
- Mantener compatibilidad con templates, JS vanilla y flujos DRF existentes. Antes de dar algo por hecho, ejecutar `pytest`.
- Para UI/CSS usar el subagente `ui-designer`; para tests, `unit-test-creator`. (AGENTS.md menciona un `code-reviewer` que **no existe** en `.claude/agents/`; usar `/code-review`.)
- No hacer cambios en producción ni operaciones destructivas (`purge_expired --apply`, borrados, migraciones sobre datos reales) sin confirmación.

## Notas y deuda conocida

- `docs/plan-ocr.md` es el plan original y el registro de decisiones por hito (H0–H10). Su tabla de hallazgos (§2) describe el estado **previo** a H0 y está en su mayor parte resuelta; usar solo las secciones de «Estado de implementación» y «decisiones».
- Pendiente: renovar al sistema visual nuevo la exportación y su previsualización (`/documents/export/`, `/documents/export/preview/`, `export_preview.css`) y barrer los botones/modales fuera de `ui.css` (`document_rectify.css` es una copia del CSS antiguo del detalle).
- Pendiente de datos reales: calibrar umbrales de auto-aprobación con un dataset de evaluación; probar Batch API con clave real; firmar los DPA (Anthropic, Cloudflare) antes de procesar facturas reales; confirmar la retención con el asesor.
- Sin gestión de etiquetas (renombrar, borrar, colores), sin mover carpetas manuales de padre, ni asignación masiva («Mover a carpeta») desde las tablas; `Role` existe pero ninguna vista lo usa para autorizar.
- `Dockerfile` instala primero `weasyprint==59.0` y luego `requirements.txt` fija 60.2 (prevalece este).

## Vista «Archivo» (Drive)

- `/documents/archivo/` (`documents:drive`, `DocumentDriveView`): documentos en carpetas **virtuales y derivadas**, sin guardar nada: `Compras|Ventas → año → trimestre → empresa → grupo de tipo`. Lógica en `selectors/drive_selector.py`; la ruta (`DrivePath.parse`) se valida y una ruta inválida o un tercero de otro cliente da 404.
- Mapeo de flujo: `out` = Compras (gasto), `in` = Ventas (ingreso). Trimestre por `issue_date`. Los grupos de tipo salen de `TYPE_GROUPS` (tipo nuevo sin grupo → «Otros»).
- Un documento al que falte fecha, tercero o flujo, o que no esté `processed`, va a «Sin clasificar» (con el motivo) y salta solo a su carpeta al corregirse.
- No confundir: la «carpeta» del Drive es *derivada*; `Folder` es una agrupación *manual*. Carpeta manual, etiqueta y estado son filtros transversales (`?folder=&tag=&status=`), no parte de la ruta del árbol derivado.
- **«Mis carpetas»** (`mis-carpetas/` y `mis-carpetas/<id>/`): árbol de `Folder` manuales **anidadas** (`Folder.parent`, máx. `folders.MAX_DEPTH`=5, nombre único entre hermanas, el padre se fija al crear: no hay ciclos). Un documento está a la vez en su carpeta derivada y en su carpeta manual (una sola). Lógica en `services/folders.py` (`create/rename/delete_folder`, `with_labels`: etiqueta «A / B» para los selects); endpoint `POST /documents/archivo/carpetas/` (`documents:drive_folder`, `action=create|rename|delete`). Borrar se bloquea con subcarpetas; los documentos de una carpeta borrada quedan sin carpeta. Las carpetas de otro cliente dan 404.
- **Categoría de documento** (`DocumentCategory`): ya no se muestra en la interfaz (nunca hubo forma de crearlas). El modelo, `Document.category`, el filtro del selector y el desglose de métricas siguen ahí por si se retoma.
- Los totales por carpeta suman `total_amount` con signo (`signed_amount`) de todos los tipos del nivel; «Sin clasificar» no muestra importe.
