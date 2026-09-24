# Multi-stage production image: React frontend + FastAPI backend.
#
# Stages
#   frontend-build  node:20-alpine   builds the Vite bundle and the browser extension
#   wheels          python:3.12-slim compiles every Python dependency into wheels
#                                    (python3-saml needs libxml2/xmlsec headers
#                                    and a C toolchain; nothing else does)
#   runtime         python:3.12-slim installs the wheels only — no compilers,
#                                    no -dev headers — plus Tesseract and the
#                                    Playwright Chromium used for PDF export.
#
# Dependencies come from backend/requirements.lock (hashes verified); the
# image cannot silently pick up a newer transitive version than CI tested.
# Base tags are pinned by version here; Renovate (renovate.json) adds and
# maintains the @sha256 digests.

FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
# npm ci: install exactly what CI tested; fails loudly if the lockfile is missing or drifts.
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build


FROM python:3.12-slim AS wheels
WORKDIR /build
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        build-essential pkg-config libxml2-dev libxmlsec1-dev libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock .
# --require-hashes: every artifact must match the lock; sdists (python3-saml)
# are built here once and shipped to the runtime stage as wheels.
RUN pip wheel --no-cache-dir --require-hashes --wheel-dir /wheels -r requirements.lock


FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/alpha_router

# Runtime-only system packages: xmlsec shared libraries (no headers) for
# SAML, Tesseract for knowledge OCR, curl for healthchecks.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        curl ca-certificates \
        libxml2 libxmlsec1 libxmlsec1-openssl \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-fas \
    && rm -rf /var/lib/apt/lists/*

# The wheel stage already verified every download against the lock's hashes;
# wheels built there from an sdist (python3-saml) have new hashes, so this
# stage installs the wheel set itself, offline, and asserts consistency.
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/*.whl \
    && pip check \
    && rm -rf /wheels

# Install Playwright's headless Chromium + system deps for server-side PDF
# rendering (chat export & activity PDF). Pinned to a system-wide path so the
# non-root runtime user can read it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 playwright install --with-deps chromium

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=frontend-build /fe/dist ./frontend/dist
# The browser extension's neutral build; the server makes each download its own
# (key, origin, version) from it.
COPY --from=frontend-build /fe/dist-extension ./frontend/dist-extension
RUN groupadd --system --gid 10001 alpha_router \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/alpha_router alpha_router \
    && mkdir -p /app/tls \
    && chown -R alpha_router:alpha_router /app /home/alpha_router

USER alpha_router

# The running version, stamped from the git tag by scripts/install.sh and
# scripts/upgrade.sh (see resolve_app_version in scripts/lib/stack.sh).
#
# Baked into the image rather than injected at run time on purpose. `upgrade.sh
# --skip-build` pulls new code without rebuilding; a version read from the
# environment would then label the old image with the new tag, and a version
# string that lies is worse than one that is missing. As an image property it
# cannot disagree with the code it was built from.
#
# Declared here, after every expensive layer, because an ARG invalidates the
# build cache from its own line onward - putting it at the top would rebuild
# apt, the wheels and Chromium on every new tag.
ARG APP_VERSION=""
ARG APP_REVISION=""
ENV APP_VERSION=${APP_VERSION} APP_REVISION=${APP_REVISION}
LABEL org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_REVISION}" \
      org.opencontainers.image.title="Alpharouter" \
      org.opencontainers.image.source="https://github.com/Arasskhani/alpha-router"

EXPOSE 8080
ENV DATABASE_URL=postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
