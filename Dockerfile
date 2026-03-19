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
    libgdk-pixbuf2.0-0 \
    libgdk-pixbuf2.0-dev \
    libffi-dev \
    libglib2.0-0 \
    libglib2.0-dev \
<<<<<<< HEAD
=======
    libpangocairo-1.0-0 \
>>>>>>> 300a5c0aa5a8a747131a232a1a81eb6e23e9b07b
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la app
COPY . .

# Crear carpeta para staticfiles
RUN mkdir -p /app/staticfiles

# Copiar el script de entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# CMD usa el entrypoint para arrancar collectstatic y luego gunicorn
CMD ["/app/entrypoint.sh"]
