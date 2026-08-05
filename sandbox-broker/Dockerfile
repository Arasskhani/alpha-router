FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/alpha_router

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG DOCKER_CLI_VERSION=27.3.1
RUN curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && chmod +x /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

RUN pip install --no-cache-dir fastapi uvicorn \
    && groupadd --system --gid 10001 alpha_router \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/alpha_router --shell /usr/sbin/nologin alpha_router \
    && chown -R alpha_router:alpha_router /srv /home/alpha_router

COPY backend/app/__init__.py /srv/app/__init__.py
COPY backend/app/branding.py /srv/app/branding.py
COPY backend/app/sandbox_broker.py /srv/broker.py
RUN chown -R alpha_router:alpha_router /srv/app /srv/broker.py

# Non-root process. Compose adds the host docker.sock group (gid 0 on Desktop)
# via group_add so the broker can still call the Docker API without uid 0.
USER alpha_router

EXPOSE 8081
HEALTHCHECK --interval=5s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2)"]

CMD ["uvicorn", "broker:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
