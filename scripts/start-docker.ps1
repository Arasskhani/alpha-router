# NITRO - Docker production stack
# Starts all services via docker-compose: PostgreSQL, Redis, MinIO, NITRO app container
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed. Install Docker Desktop, then retry." -ForegroundColor Red
    exit 1
}

try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "daemon not running" }
} catch {
    Write-Host "Docker is not running. Start Docker Desktop, then retry." -ForegroundColor Red
    exit 1
}

Write-Host "==> NITRO Docker stack (PostgreSQL + Redis + MinIO + app)" -ForegroundColor Cyan
Write-Host "==> Building and starting containers..." -ForegroundColor Cyan
docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "NITRO:         http://localhost:8080  (wait ~30s on first build)" -ForegroundColor Green
Write-Host "MinIO console: http://localhost:9001  (nitro / ***REMOVED***)" -ForegroundColor Yellow
Write-Host "PostgreSQL:    localhost:5432  (nitro / nitro)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Following nitro container logs (Ctrl+C to stop watching; containers keep running)..." -ForegroundColor Cyan
docker compose logs -f nitro
