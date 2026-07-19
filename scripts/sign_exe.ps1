# Sign Nexuz.exe with Authenticode (signtool).
#
# Usage:
#   .\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe -PfxPath cert.pfx -Password "xxx"
#   .\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe   # env: WINDOWS_CERTIFICATE_FILE / PASSWORD
#
# Self-signed certs are OK. We do NOT use `signtool verify /pa` (fails without trusted root
# and leaves a non-zero process exit code that breaks GitHub Actions pwsh steps).

param(
  [Parameter(Mandatory = $true)]
  [string]$ExePath,

  [string]$PfxPath = "",
  [string]$Password = "",
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = 0

if (-not (Test-Path -LiteralPath $ExePath)) {
  throw "Exe not found: $ExePath"
}

if (-not $Password) {
  $Password = $env:WINDOWS_CERTIFICATE_PASSWORD
}
if (-not $PfxPath) {
  $PfxPath = $env:WINDOWS_CERTIFICATE_FILE
}

if (-not $PfxPath -or -not (Test-Path -LiteralPath $PfxPath)) {
  throw "PFX not found. Pass -PfxPath or set WINDOWS_CERTIFICATE_FILE"
}
if (-not $Password) {
  throw "PFX password required. Pass -Password or set WINDOWS_CERTIFICATE_PASSWORD"
}

$Password = "$Password".Trim()
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
$PfxPath = (Resolve-Path -LiteralPath $PfxPath).Path

function Find-SignTool {
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $roots = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
    "${env:ProgramFiles}\Windows Kits\10\bin"
  )
  foreach ($root in $roots) {
    if (-not (Test-Path $root)) { continue }
    $hit = Get-ChildItem -Path $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  throw "signtool.exe not found. Install Windows SDK / Build Tools."
}

function Invoke-SignTool {
  param([string[]]$SignArgs)
  $output = & $script:signtool @SignArgs 2>&1
  $code = $LASTEXITCODE
  $global:LASTEXITCODE = 0
  if ($output) {
    $output | ForEach-Object { Write-Host $_ }
  }
  return $code
}

$script:signtool = Find-SignTool
Write-Host "Using signtool: $signtool"
Write-Host "Signing: $ExePath"

$signCode = Invoke-SignTool @(
  "sign",
  "/f", $PfxPath,
  "/p", $Password,
  "/fd", "sha256",
  "/tr", $TimestampUrl,
  "/td", "sha256",
  "/d", "Nexuz",
  $ExePath
)

if ($signCode -ne 0) {
  Write-Host "Timestamped sign failed (exit $signCode); retry without timestamp..."
  $signCode = Invoke-SignTool @(
    "sign",
    "/f", $PfxPath,
    "/p", $Password,
    "/fd", "sha256",
    "/d", "Nexuz",
    $ExePath
  )
  if ($signCode -ne 0) {
    throw "signtool sign failed with exit $signCode"
  }
}

$sig = Get-AuthenticodeSignature -FilePath $ExePath
if ($null -eq $sig.SignerCertificate -or $sig.Status -eq "NotSigned") {
  throw "signature missing after signtool (Status=$($sig.Status))"
}

Write-Host "Authenticode Status=$($sig.Status)"
Write-Host "Subject=$($sig.SignerCertificate.Subject)"
Write-Host "Thumbprint=$($sig.SignerCertificate.Thumbprint)"
Write-Host "OK: signed $ExePath"
$global:LASTEXITCODE = 0
