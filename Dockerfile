# Multi-stage production image: React frontend + FastAPI backend
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/alpha-router

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates pkg-config \
        libxml2-dev libxmlsec1-dev libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /fe/dist ./frontend/dist
RUN groupadd --system --gid 10001 alpha-router \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/alpha-router alpha-router \
    && chown -R alpha_router:alpha-router /app /home/alpha-router

USER alpha-router

EXPOSE 8080
ENV DATABASE_URL=postgresql+asyncpg://alpha_router:alpha_router@postgres:5432/alpha-router
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
