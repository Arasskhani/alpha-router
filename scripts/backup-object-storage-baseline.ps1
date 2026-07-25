# Inventory SeaweedFS / S3 objects and optionally tar the SeaweedFS Docker volume.
# Usage:
#   .\scripts\backup-object-storage-baseline.ps1
#   .\scripts\backup-object-storage-baseline.ps1 -IncludeVolumeTar
# Outputs under .\backups\object-storage\<timestamp>\
param(
    [switch]$IncludeVolumeTar,
    [string]$EndpointUrl = "",
    [string]$Bucket = "",
    [string]$AccessKey = "",
    [string]$SecretKey = "",
    [string]$VolumeName = ""
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

function ConvertTo-HostReachableS3Url {
    param([string]$Url)
    if (-not $Url) { return $Url }
    $u = $Url.Trim()
    # Compose DNS names only resolve inside the Docker network.
    $u = $u -replace "(?i)https?://seaweedfs(:\d+)?", "http://127.0.0.1:8333"
    return $u
}

function Resolve-SeaweedVolumeName {
    param([string]$Preferred)
    if ($Preferred) { return $Preferred }
    $names = @()
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $names = @(docker volume ls --format "{{.Name}}" 2>$null)
        $ErrorActionPreference = $prev
    } catch {
        $names = @()
    }
    $match = $names | Where-Object { $_ -match "alpha_router_seaweedfs$" } | Select-Object -First 1
    if ($match) { return $match }
    return "alpha_router_seaweedfs"
}

if (-not $EndpointUrl) { $EndpointUrl = Read-DotEnvValue "S3_ENDPOINT_URL" }
if (-not $EndpointUrl) { $EndpointUrl = "http://127.0.0.1:8333" }
$EndpointUrl = ConvertTo-HostReachableS3Url $EndpointUrl
if (-not $Bucket) { $Bucket = Read-DotEnvValue "S3_BUCKET" }
if (-not $Bucket) { $Bucket = "alpha-router-media" }
if (-not $AccessKey) { $AccessKey = Read-DotEnvValue "S3_ACCESS_KEY" }
if (-not $SecretKey) { $SecretKey = Read-DotEnvValue "S3_SECRET_KEY" }
$VolumeName = Resolve-SeaweedVolumeName -Preferred $VolumeName

if (-not $AccessKey -or -not $SecretKey) {
    Write-Host "S3_ACCESS_KEY / S3_SECRET_KEY required (.env or parameters)." -ForegroundColor Red
    exit 1
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $Root "backups\object-storage\$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$manifestPath = Join-Path $outDir "manifest.jsonl"
$summaryPath = Join-Path $outDir "summary.txt"
$py = @"
import json, sys
import boto3
from botocore.client import Config

endpoint, bucket, ak, sk, out = sys.argv[1:6]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=ak,
    aws_secret_access_key=sk,
    region_name="us-east-1",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
count = 0
total = 0
with open(out, "w", encoding="utf-8") as fh:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents") or []:
            row = {
                "key": obj.get("Key"),
                "size": int(obj.get("Size") or 0),
                "etag": (obj.get("ETag") or "").strip('"'),
                "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            total += row["size"]
print(f"objects={count}")
print(f"bytes={total}")
"@

$pyFile = Join-Path $outDir "_inventory.py"
Set-Content -Path $pyFile -Value $py -Encoding UTF8

Write-Host "==> Inventory $Bucket at $EndpointUrl" -ForegroundColor Cyan
$inv = & python $pyFile $EndpointUrl $Bucket $AccessKey $SecretKey $manifestPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "Inventory failed. Is the object store running and reachable?" -ForegroundColor Red
    exit 1
}
$inv | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host ($inv -join "`n") -ForegroundColor Green

if ($IncludeVolumeTar) {
    Write-Host "==> Tar Docker volume $VolumeName (requires docker)" -ForegroundColor Cyan
    $tarPath = "/backup/seaweedfs-volume-$stamp.tar.gz"
    docker run --rm `
        -v "${VolumeName}:/data:ro" `
        -v "${outDir}:/backup" `
        alpine:3.20 `
        tar -czf $tarPath -C /data .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Volume tar failed. Check volume name with: docker volume ls" -ForegroundColor Yellow
        Write-Host "Common name: <project>_alpha_router_seaweedfs (e.g. alpha_router_seaweedfs)" -ForegroundColor Yellow
        exit 1
    }
    $found = Get-ChildItem $outDir -Filter "seaweedfs-volume-*.tar.gz" | Select-Object -First 1
    if ($found) { Write-Host "Volume backup: $($found.FullName)" -ForegroundColor Green }
}

Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Baseline written to: $outDir" -ForegroundColor Green
Write-Host "Keep this directory outside ephemeral disks before major changes." -ForegroundColor DarkGray
