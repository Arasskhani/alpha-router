# Windows LDAP bridge for Alpha Router Docker (signed Active Directory on port 389).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Backend venv not found. Run: cd backend; python -m venv .venv; pip install -r requirements.txt"
}

if (-not $env:LDAP_BRIDGE_TOKEN) {
    $env:LDAP_BRIDGE_TOKEN = "alpha-router-ldap-bridge"
}

$Port = if ($env:LDAP_BRIDGE_PORT) { $env:LDAP_BRIDGE_PORT } else { "8765" }
Write-Host "Starting Alpha Router LDAP bridge on http://0.0.0.0:$Port (token set: $($env:LDAP_BRIDGE_TOKEN -ne ''))"
Set-Location $Backend
& $VenvPython -m uvicorn app.ldap_bridge_server:app --host 0.0.0.0 --port $Port
