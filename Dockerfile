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

# Önce sadece requirements.txt kopyala (layer cache için de iyi olur)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Şimdi proje dosyalarını kopyala
COPY . .

# Kendi paketini bağımlılıkları TEKRAR ÇÖZMEDEN kur
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000

CMD ["uvicorn", "asgi_app:app", "--host", "0.0.0.0", "--port", "8000"]