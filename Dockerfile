FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Sistem bağımlılıklarını güncelle
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# pip'i güncelle
RUN pip install --no-cache-dir --upgrade pip

# Tüm proje dosyalarını (pyproject.toml dahil) kopyala
COPY . .

# pyproject.toml üzerinden projeyi ve bağımlılıklarını kur
RUN pip install --no-cache-dir .

# Konteyner içi port
EXPOSE 8000

# Uygulama başlatma komutu
CMD ["uvicorn", "asgi_app:app", "--host", "0.0.0.0", "--port", "8000"]