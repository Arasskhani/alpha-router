# Multi-stage production image: React frontend + FastAPI backend
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/alpha_router

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        build-essential curl ca-certificates pkg-config \
        libxml2-dev libxmlsec1-dev libxmlsec1-openssl \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-fas \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's headless Chromium + system deps for server-side PDF
# rendering (chat export & activity PDF). Pinned to a system-wide path so the
# non-root runtime user can read it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 playwright install --with-deps chromium

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=frontend-build /fe/dist ./frontend/dist
RUN groupadd --system --gid 10001 alpha_router \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/alpha_router alpha_router \
    && chown -R alpha_router:alpha_router /app /home/alpha_router

USER alpha_router

EXPOSE 8080
ENV DATABASE_URL=postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
