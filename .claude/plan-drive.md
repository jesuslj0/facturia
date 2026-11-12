# Plan: vista «Archivo» (Drive por carpetas)

Estado: propuesta · Proyecto: FacturIA (`billing_ai`) · Sin migraciones

## Objetivo

Una vista nueva, estilo Drive, que muestre los documentos en carpetas **sin que nadie
las cree ni mueva documentos**: al subir y procesar un documento, aparece ya en su sitio.
Reproduce la estructura antigua (año → trimestre → empresa → facturas / albaranes / abonos)
y la une con lo nuevo (flujo, categoría, carpeta manual, etiquetas).

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Ventas | El tercero de una venta es el **cliente** de la factura; en una compra, el **proveedor**. Ambos son `Company`. |
| Trimestre | Por **fecha de emisión** (`issue_date`), la fecha fiscal. No por fecha de subida. |
| Tickets y presupuestos | Dentro de la carpeta de cada empresa, como una carpeta más. |
| Enfoque | **Árbol virtual calculado** a partir de los datos. No se guarda ninguna carpeta en la base de datos. |

## Estructura del árbol

```
Compras | Ventas                  ← flow: out = Compras (gasto), in = Ventas (ingreso)
 └─ 2026                          ← año de issue_date
     └─ T1                        ← trimestre de issue_date
         └─ Proveedor S.L.        ← Company (por id; el nombre es solo para mostrar)
             ├─ Facturas          ← invoice
             ├─ Albaranes         ← delivery
             ├─ Abonos            ← corrected_invoice + delivery_credit_note
             ├─ Tickets           ← receipt
             └─ Presupuestos      ← quote
 └─ Sin clasificar                ← ver abajo
```

Cuidado con el flujo: en el modelo `flow="in"` es **Ingreso (venta)** y `flow="out"` es
**Gasto (compra)**. El primer nivel se muestra «Compras | Ventas», pero el mapeo es
`out → Compras`, `in → Ventas`. Ponerlo en una constante y cubrirlo con un test.

### Agrupación de tipos (una sola fuente de verdad)

Un diccionario en el servicio, no repartido por plantillas:

```python
TYPE_GROUPS = {            # slug en la URL -> (etiqueta, tipos de Document.TYPE_CHOICES)
    "facturas":     ("Facturas",     ["invoice"]),
    "albaranes":    ("Albaranes",    ["delivery"]),
    "abonos":       ("Abonos",       ["corrected_invoice", "delivery_credit_note"]),
    "tickets":      ("Tickets",      ["receipt"]),
    "presupuestos": ("Presupuestos", ["quote"]),
}
```

Si mañana se añade un tipo a `Document.TYPE_CHOICES` y no está aquí, debe caer en una
carpeta «Otros» y no desaparecer (test que compare ambos conjuntos).

### Carpeta «Sin clasificar»

Un documento no puede estar en el árbol si le falta algún dato de la ruta. Va a
«Sin clasificar», con el motivo visible, si cumple cualquiera de estas condiciones:

- `issue_date` vacío.
- `company` vacía.
- `flow == "unknown"` (Por revisar).
- `processing_status` distinto de `processed` (en cola, procesando o `failed`).

Es importante: si no, un fallo del OCR haría desaparecer el documento del Drive.
En cuanto se corrige el dato (a mano o con reintento), salta solo a su carpeta.

## Reglas de consulta

- Base: `DocumentSelector.for_client(client)` (ya filtra por cliente y `is_current=True`)
  y **excluye archivados** (`is_archived=False`), igual que el listado.
- Las versiones anteriores de una rectificación no salen en el árbol; se llega a ellas
  desde el detalle.
- Pendientes, aprobados y rechazados aparecen juntos, con el badge de estado existente
  (`{% badge 'review' … %}`). Filtro opcional «Solo aprobados» para preparar impuestos.
- Aislamiento por tenant: toda consulta parte del cliente del usuario. Un `company_id`
  de otro cliente da **404**, no carpeta vacía.

## Cambios por capa

### 1. Servicio / selector (lógica, sin vistas)

Nuevo `documents/selectors/drive_selector.py` (o un método en `DocumentSelector`):

- `children(client, path, filters)` → devuelve las carpetas hijas del nivel actual,
  cada una con `nombre`, `slug`, `count`, `total` (suma de importes con signo) y
  `pending_count`.
- `documents(client, path, filters)` → documentos del nivel hoja (empresa + grupo de tipo),
  paginados con `billing_ai/listing.py`.
- Año y trimestre con `ExtractYear` y `ExtractQuarter` + `.values().annotate(Count)`.
  Ya existe `quarter_range('2026-T2')` en `document_selector.py` para filtrar un trimestre.
- Importes: usar `signed_amount` / `document_sign` de `services/signs.py` (una rectificativa
  **resta siempre**). No inventar otra suma.
- Excluir de los totales las carpetas «Sin clasificar» o marcarlas aparte: sin fecha o sin
  flujo el importe no es fiable.

La ruta se representa como un objeto pequeño, p. ej. `DrivePath(flow, year, quarter, company_id, group)`,
construido a partir de la URL y validado (año de 4 cifras, trimestre 1–4, grupo en `TYPE_GROUPS`).
Una ruta no válida devuelve 404.

### 2. Vista y URLs

En `documents/views.py`, una CBV fina (`DocumentDriveView`, con `LoginRequiredMixin`):

```
/documents/archivo/                                         raíz: Compras | Ventas | Sin clasificar
/documents/archivo/<flow>/                                  años
/documents/archivo/<flow>/<year>/                           trimestres
/documents/archivo/<flow>/<year>/T<q>/                      empresas
/documents/archivo/<flow>/<year>/T<q>/<company_id>/         grupos de tipo
/documents/archivo/<flow>/<year>/T<q>/<company_id>/<grupo>/ documentos
/documents/archivo/sin-clasificar/                          documentos sin clasificar
```

`app_name = "documents"`, nombre `documents:drive`. Un solo patrón con `<path:ruta>` y
parseo en el servicio es más sencillo que cinco rutas. Añadir la entrada al menú lateral
(`templates/base.html`) junto a «Documentos».

### 3. Plantilla y UI

`templates/private/documents/document_drive.html` + `static/css/documents/document_drive.css`
+ `static/js/drive.js` (solo si hace falta vista cuadrícula/lista).

- **Migas de pan** clicables: `Compras › 2026 › T1 › Proveedor S.L.`.
- Carpetas como tarjetas con icono `{% icon "folder" %}` (ya existe), nombre y contador;
  en lista o cuadrícula.
- En la hoja, tabla de documentos reutilizando las filas del listado actual
  (extraer a un parcial `components/_document_rows.html` si hace falta, sin duplicar).
- Barra de filtros transversales en cualquier nivel: **categoría, carpeta manual, etiqueta,
  estado**. Reutilizar `get_filtered_documents`; `billing_ai/listing.py` pinta los chips.
- Usar los tokens de `ui.css` (`.btn`, `.chip`, `.badge-status`). Sin `!important` ni estilos
  en línea. Usar el subagente `ui-designer` para la plantilla.
- Estado vacío claro: «Aún no hay documentos en esta carpeta».

### 4. Carpeta, categoría y etiqueta

No entran en la ruta. Son ejes transversales:

- `Folder` pasa a ser una **agrupación manual** («Inmueble Calle X», «Pendiente gestoría»)
  que se puede filtrar dentro del Drive.
- `DocumentCategory` y `Tag`, igual: filtros y chips.
- Documentar en `CLAUDE.md` que «carpeta» en el Drive es *virtual y derivada*, y `Folder`
  es *manual*, para que no se confundan.

## Tests (`documents/tests/test_drive.py`)

- Un documento procesado aparece en `Compras/2026/T1/<empresa>/Facturas` sin ninguna acción.
- Frontera de trimestres: 31 mar → T1, 1 abr → T2, 31 dic → T4, 1 ene → siguiente año.
- Corregir fecha / empresa / tipo mueve el documento de carpeta.
- `corrected_invoice` y `delivery_credit_note` caen en «Abonos»; `receipt` y `quote` dentro de la empresa.
- `flow=unknown`, sin fecha, sin empresa, `failed` y `processing` → «Sin clasificar».
- Todos los valores de `Document.TYPE_CHOICES` están en `TYPE_GROUPS` (o caen en «Otros»).
- Compras = `out`, Ventas = `in`.
- Archivados y versiones no vigentes no salen.
- **Aislamiento**: el cliente A no ve carpetas de B; `company_id` de B → 404.
- Totales con signo: una rectificativa resta.
- Ruta inválida (año `abc`, `T9`, grupo desconocido) → 404.
- Sin importes, empresa sin NIF, carpeta vacía.

## Fases

1. **Fase 1 (este plan):** selector + vista + plantilla + menú + tests.
2. **Fase 2: descargar carpeta como ZIP** con `2026/T1/Proveedor S.L./Facturas/…` (para la gestoría).
   Hay que sanear los nombres de empresa para rutas de archivo, evitar colisiones de nombres
   (usar el nº de documento o el id) y limitar tamaño/nº de archivos. Los archivos se sirven
   de R2 por vistas autenticadas, nunca con URL pública. Hacer la generación en Celery si
   la carpeta es grande.
3. **Fase 3: reglas de archivado** («si tercero = X → categoría/carpeta/etiqueta Y») aplicadas
   en `apply_extraction`, para que también esos ejes se rellenen solos al procesar.
   Es la forma de cubrir la «gestión de carpetas/etiquetas» que el CLAUDE.md anota como pendiente.

## Riesgos y cosas a vigilar

- **Rendimiento.** Con muchos documentos, los contadores por nivel deben salir de una sola
  consulta agrupada por nivel, no de una consulta por carpeta. Comprobar con `django-debug-toolbar`
  que no hay N+1 en la lista de empresas. Índice existente: `(client, issue_date)`;
  valorar `(client, flow, issue_date)` solo si las consultas lo piden.
- **Terceros duplicados.** Si el mismo proveedor está duplicado, saldrá en dos carpetas.
  Ya existe `manage.py merge_companies`; mencionarlo en la ayuda de la vista.
- **Zona horaria.** `TIME_ZONE="UTC"` y `issue_date` es un `DateField`, así que no hay
  desplazamientos de día en el trimestre.
- **Nombres de empresa** en la URL: usar siempre el `id`, nunca el nombre.
- **No** modificar claves de R2 ni el archivo almacenado (el preprocesado no lo toca nunca).
- Si se toca `Document.save()` o se hacen cargas masivas, recordar que llama a `full_clean()`.

## Fuera de alcance (por ahora)

Arrastrar y soltar para mover entre carpetas (no tiene sentido en un árbol derivado),
permisos por carpeta, compartir carpetas, y renombrar o borrar carpetas manuales
(sigue pendiente en el CLAUDE.md).
