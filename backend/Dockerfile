# Beyonder backend image.
#
# Deliberately browser-free: URL ingestion runs SCRAPER_BACKEND=http in the
# cloud, which keeps the image near 400 MB and the container inside a 512 MB
# free-tier instance. Run Playwright locally when a site needs JavaScript.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# lxml and psycopg[binary] ship wheels, so no compiler is needed. curl is here
# for the container healthcheck only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Never run as root.
RUN useradd --create-home --uid 10001 beyonder \
    && chown -R beyonder:beyonder /app
USER beyonder

ENV PORT=8000 \
    SCRAPER_BACKEND=http
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Hosts (Render, Fly, Koyeb, Cloud Run) inject $PORT. Default to 8000 locally.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
