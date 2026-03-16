# Slim Python base keeps image size and startup time low.
FROM python:3.11-slim

# Avoid .pyc files and force immediate log flushing.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Application root inside the container.
WORKDIR /app

# Install dependencies first to maximize Docker layer cache reuse.
COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

# Copy source code after dependencies.
COPY . .

EXPOSE 8000

# Use Gunicorn with Uvicorn workers; default workers = CPU cores, override via WEB_CONCURRENCY.
CMD ["sh", "-c", "WORKERS=${WEB_CONCURRENCY:-$(python -c 'import os; print(os.cpu_count() or 1)')}; exec gunicorn main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 -w \"$WORKERS\""]
