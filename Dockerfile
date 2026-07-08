# Multi-stage production image: React frontend + FastAPI backend
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /fe/dist ./frontend/dist

EXPOSE 8080
ENV DATABASE_URL=postgresql+asyncpg://nitro:nitro@postgres:5432/nitro
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
