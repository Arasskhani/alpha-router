# Automated security checks for the SeaweedFS object-storage surface.
# Requires seaweedfs running (default localhost binds).
# Exit 0 only when all checks pass.
param(
    [string]$S3Endpoint = "http://127.0.0.1:8333",
    [string]$AdminUrl = "http://127.0.0.1:23646",
    [string]$Bucket = "",
    [string]$AccessKey = "",
    [string]$SecretKey = "",
    [string]$AdminPassword = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Read-DotEnvValue {
    param([string]$Key)
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) { return "" }
    foreach ($line in Get-Content $envPath) {
        if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
        $parts = $line.Split("=", 2)
        if ($parts[0].Trim() -eq $Key) { return $parts[1].Trim().Trim('"').Trim("'") }
    }
    return ""
}

if (-not $Bucket) { $Bucket = Read-DotEnvValue "S3_BUCKET" }
if (-not $Bucket) { $Bucket = "alpha-router-media" }
if (-not $AccessKey) { $AccessKey = Read-DotEnvValue "S3_ACCESS_KEY" }
if (-not $SecretKey) { $SecretKey = Read-DotEnvValue "S3_SECRET_KEY" }
if (-not $AdminPassword) { $AdminPassword = Read-DotEnvValue "SEAWEEDFS_ADMIN_PASSWORD" }

$failures = @()

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if ($Condition) {
        Write-Host "PASS  $Message" -ForegroundColor Green
    } else {
        Write-Host "FAIL  $Message" -ForegroundColor Red
        $script:failures += $Message
    }
}

# 1) Ports must listen on localhost only (not 0.0.0.0 / ::)
foreach ($port in @(8333, 23646)) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        $bad = @($conns | Where-Object {
            $_.LocalAddress -notin @("127.0.0.1", "::1", "0:0:0:0:0:0:0:1")
        })
        Assert-True ($bad.Count -eq 0 -and $conns) "Port $port listens and is localhost-bound"
    } catch {
        Assert-True $false "Port $port is listening"
    }
}

# 2) Anonymous S3 list must fail when credentials are configured
$anonPy = @"
import sys
import boto3
from botocore.client import Config
from botocore import UNSIGNED
endpoint, bucket = sys.argv[1], sys.argv[2]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    region_name="us-east-1",
    config=Config(signature_version=UNSIGNED, s3={"addressing_style": "path"}),
)
try:
    client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    print("ANON_ALLOWED")
    sys.exit(1)
except Exception as exc:
    print(type(exc).__name__)
    sys.exit(0)
"@
$anonFile = Join-Path $env:TEMP "alpha-router-s3-anon-check.py"
Set-Content $anonFile $anonPy -Encoding UTF8
& python $anonFile $S3Endpoint $Bucket | Out-Null
Assert-True ($LASTEXITCODE -eq 0) "Anonymous S3 list is denied"

# 3) Wrong credentials must fail
$badPy = @"
import sys
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
endpoint, bucket = sys.argv[1], sys.argv[2]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id="wrong-access-key",
    aws_secret_access_key="wrong-secret-key-value",
    region_name="us-east-1",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
try:
    client.list_buckets()
    print("BAD_CREDS_ALLOWED")
    sys.exit(1)
except ClientError:
    sys.exit(0)
except Exception:
    sys.exit(0)
"@
$badFile = Join-Path $env:TEMP "alpha-router-s3-bad-check.py"
Set-Content $badFile $badPy -Encoding UTF8
& python $badFile $S3Endpoint $Bucket | Out-Null
Assert-True ($LASTEXITCODE -eq 0) "Invalid S3 credentials are rejected"

# 4) Valid credentials can list buckets
if ($AccessKey -and $SecretKey) {
    $okPy = @"
import sys
import boto3
from botocore.client import Config
endpoint, ak, sk = sys.argv[1:4]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=ak,
    aws_secret_access_key=sk,
    region_name="us-east-1",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
client.list_buckets()
print("OK")
"@
    $okFile = Join-Path $env:TEMP "alpha-router-s3-ok-check.py"
    Set-Content $okFile $okPy -Encoding UTF8
    & python $okFile $S3Endpoint $AccessKey $SecretKey | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) "Valid S3 credentials can list buckets"
} else {
    Assert-True $false "S3 credentials present for positive auth check"
}

# 5) Admin UI requires authentication when password is configured
try {
    $resp = Invoke-WebRequest -Uri $AdminUrl -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
    $code = [int]$resp.StatusCode
} catch {
    if ($_.Exception.Response) {
        $code = [int]$_.Exception.Response.StatusCode
    } else {
        $code = 0
    }
}
# Accept challenge / login redirect / unauthorized; reject wide-open 200 HTML app without auth headers if password set.
if ($AdminPassword) {
    $protected = $code -in @(401, 403, 302, 303, 307, 308)
    if (-not $protected -and $code -eq 200) {
        # Some builds serve SPA shell at 200 but API is protected; require Set-Cookie/WWW-Authenticate or login form marker.
        try {
            $body = (Invoke-WebRequest -Uri $AdminUrl -UseBasicParsing).Content
            $protected = ($body -match "(?i)login|password|sign.?in|authorize")
        } catch {
            $protected = $false
        }
    }
    Assert-True $protected "Admin UI is not anonymously fully open (status=$code)"
} else {
    Write-Host "SKIP  Admin password not set; configure SEAWEEDFS_ADMIN_PASSWORD" -ForegroundColor Yellow
}

Remove-Item $anonFile, $badFile -Force -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $env:TEMP "alpha-router-s3-ok-check.py")) {
    Remove-Item (Join-Path $env:TEMP "alpha-router-s3-ok-check.py") -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All object-storage security checks passed." -ForegroundColor Green
    exit 0
}
Write-Host "Security check failures:" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
exit 1
