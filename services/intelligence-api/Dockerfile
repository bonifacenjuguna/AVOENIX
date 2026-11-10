# Build context: repository root.   docker build -f services/intelligence-api/Dockerfile -t avoenix-api .
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
ENV PORT=8000 AVOENIX_ENV=production
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8000'),timeout=3)" || exit 1
# Migrations are applied explicitly (see docs/DEPLOYMENT.md): `alembic -c services/intelligence-api/alembic.ini upgrade head`
CMD ["sh", "-c", "cd services/intelligence-api && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers"]
