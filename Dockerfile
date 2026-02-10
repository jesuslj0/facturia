FROM python:3.12-slim

# Evitar .pyc y buffer en stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
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
