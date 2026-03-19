FROM python:3.12-slim

# Evitar .pyc y buffer en stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema para WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpango1.0-dev \
    libgdk-pixbuf-xlib-2.0-0 \
    libgdk-pixbuf-xlib-2.0-dev \
    libffi-dev \
    libglib2.0-0 \
    libglib2.0-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero (capa cacheable)
COPY requirements.txt .

# Instalar deps de Python, WeasyPrint actualizado y cffi
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir  "cffi>=1.15" "tinycss2>=1.2" "pyphen>=0.13" "weasyprint==59.0" \
    && pip install --no-cache-dir -r requirements.txt

# Copiar el código de la app
COPY . .

# Crear carpeta para staticfiles
RUN mkdir -p /app/staticfiles

# Copiar el script de entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# CMD usa el entrypoint para arrancar collectstatic y luego gunicorn
CMD ["/app/entrypoint.sh"]