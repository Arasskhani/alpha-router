# Windows LDAP bridge for NITRO Docker (signed Active Directory on port 389).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Backend venv not found. Run: cd backend; python -m venv .venv; pip install -r requirements.txt"
}

if (-not $env:LDAP_BRIDGE_TOKEN -and (Test-Path $EnvFile)) {
    $TokenLine = Get-Content $EnvFile | Where-Object {
        $_ -match '^\s*LDAP_BRIDGE_TOKEN='
    } | Select-Object -Last 1
    if ($TokenLine) {
        $env:LDAP_BRIDGE_TOKEN = ($TokenLine -split '=', 2)[1].Trim()
    }
}

if (-not $env:LDAP_BRIDGE_TOKEN -or $env:LDAP_BRIDGE_TOKEN.Length -lt 32) {
    Write-Error "LDAP_BRIDGE_TOKEN must be set to a random value of at least 32 characters."
}

$Port = if ($env:LDAP_BRIDGE_PORT) { $env:LDAP_BRIDGE_PORT } else { "8765" }
$BindHost = if ($env:LDAP_BRIDGE_BIND_HOST) { $env:LDAP_BRIDGE_BIND_HOST } else { "127.0.0.1" }
if ($BindHost -notin @("127.0.0.1", "::1", "localhost") -and $env:LDAP_BRIDGE_ALLOW_REMOTE_BIND -ne "true") {
    Write-Error "Remote LDAP bridge bind requires LDAP_BRIDGE_ALLOW_REMOTE_BIND=true and host firewall restrictions."
}

# The bridge process must execute LDAP locally instead of recursively calling itself.
$env:LDAP_BRIDGE_URL = ""
Write-Host "Starting NITRO LDAP bridge on http://${BindHost}:$Port (authenticated)"
Set-Location $Backend
& $VenvPython -m uvicorn app.ldap_bridge_server:app --host $BindHost --port $Port
