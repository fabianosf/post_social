FROM python:3.12-slim

WORKDIR /app

# Dependências de sistema para Pillow e instagrapi
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libffi-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Criar diretórios necessários
RUN mkdir -p data uploads sessions logs config clients

EXPOSE 5000

# Variáveis padrão (sobrescreva via .env ou docker-compose)
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "run:app"]
