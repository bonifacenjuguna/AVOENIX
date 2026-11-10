# AVOENIX API image. Build context = repository root (Railway detects this file automatically).
#   docker build -t avoenix-api .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 avoenix
WORKDIR /srv/avoenix
COPY services/intelligence-api/requirements.txt services/intelligence-api/requirements.txt
RUN pip install -r services/intelligence-api/requirements.txt
COPY intelligence intelligence
COPY services services
COPY database database
COPY evaluation evaluation
COPY VERSION pyproject.toml ./
USER avoenix
ENV AVOENIX_ENV=production
EXPOSE 8000
# Applies the (idempotent) schema when DATABASE_URL is set, then starts the API on $PORT (Railway injects PORT).
CMD ["sh", "-c", "if [ -n \"$DATABASE_URL\" ]; then python services/intelligence-api/migrate.py || exit 1; fi; cd services/intelligence-api && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
