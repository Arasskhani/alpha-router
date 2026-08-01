# Alpha Router - Stop entire stack (Docker Compose)
# Stops: alpha app, PostgreSQL, Redis, SeaweedFS, and related compose services.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$AlphaRouterPorts = @(8080, 5432, 6379, 8333, 23646)

function Write-Step {
    param([string]$Message)
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Stop-DockerStack {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "Docker CLI not found - skipping compose shutdown." -ForegroundColor Yellow
        return
    }

    $daemonUp = $true
    try {
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { $daemonUp = $false }
    } catch {
        $daemonUp = $false
    }

    if (-not $daemonUp) {
        Write-Host "Docker daemon is not running - no compose containers to stop." -ForegroundColor Yellow
        return
    }

    Write-Step "Stopping Docker Compose stack: alpha, postgres, redis, seaweedfs"
    docker compose down --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("docker compose down failed with exit code " + $LASTEXITCODE + ".") -ForegroundColor Red
        exit 1
    }
}

function Test-PortListening {
    param([int]$Port)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        return [bool]$conn
    } catch {
        return $false
    }
}

function Get-ComposeContainerCount {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return 0 }
    try {
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return 0 }
    } catch {
        return 0
    }
    $ids = docker compose ps -q 2>$null
    if (-not $ids) { return 0 }
    return @($ids | Where-Object { $_ -match "\S" }).Count
}

Write-Host ""
Write-Host "Alpha Router - shutdown all services" -ForegroundColor Cyan
Write-Host ""

Stop-DockerStack

Write-Host ""
Write-Step "Verifying shutdown"

$issues = @()

$containerCount = Get-ComposeContainerCount
if ($containerCount -gt 0) {
    $issues += "Docker Compose still has " + $containerCount + " running container(s). Run: docker compose ps"
}

foreach ($port in $AlphaRouterPorts) {
    if (Test-PortListening -Port $port) {
        $issues += "Port " + $port + " is still listening"
    }
}

if ($issues.Count -eq 0) {
    Write-Host ""
    Write-Host "All Alpha Router services appear stopped." -ForegroundColor Green
    Write-Host "  Docker stack: down - postgres, redis, seaweedfs, alpha" -ForegroundColor DarkGray
    Write-Host ("  Ports checked: " + ($AlphaRouterPorts -join ", ")) -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Data volumes were kept. To remove them too, run: docker compose down -v" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "Shutdown completed with warnings:" -ForegroundColor Yellow
foreach ($item in $issues) {
    Write-Host ("  - " + $item) -ForegroundColor Yellow
}
Write-Host ""
Write-Host "If a port is still in use, run:" -ForegroundColor DarkGray
Write-Host "  Get-NetTCPConnection -LocalPort PORT -State Listen | Select-Object OwningProcess" -ForegroundColor DarkGray
Write-Host ""
exit 1
