# Sign Nexuz.exe with Authenticode (signtool).
#
# Usage:
#   .\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe -PfxPath cert.pfx -Password "xxx"
#   .\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe   # reads WINDOWS_CERTIFICATE_PASSWORD / file from env
#
# In GitHub Actions, secrets WINDOWS_CERTIFICATE (base64 pfx) + WINDOWS_CERTIFICATE_PASSWORD are used.
#
# Note: self-signed certs will NOT pass `signtool verify /pa` (no trusted root).
# We treat "has Authenticode signer" as success for interim certs; OV/EV still pass /pa.

param(
  [Parameter(Mandatory = $true)]
  [string]$ExePath,

  [string]$PfxPath = "",
  [string]$Password = "",
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

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

$Password = $Password.Trim()

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

function Assert-HasAuthenticodeSignature {
  param([string]$Path)

  $sig = Get-AuthenticodeSignature -FilePath $Path
  if ($sig.Status -eq "NotSigned" -or -not $sig.SignerCertificate) {
    throw "signature verify failed: file is not Authenticode-signed (Status=$($sig.Status))"
  }

  Write-Host "Authenticode Status=$($sig.Status) Subject=$($sig.SignerCertificate.Subject)"
  Write-Host "Thumbprint=$($sig.SignerCertificate.Thumbprint)"

  # Preferred path for OV/EV (trusted chain). Self-signed usually fails /pa — that is OK.
  & $script:signtool verify /pa /v $Path
  if ($LASTEXITCODE -eq 0) {
    Write-Host "OK: trusted-chain verify (/pa) passed"
    return
  }

  Write-Host "WARN: signtool verify /pa failed (common for self-signed). Accepting signer presence."
}

$script:signtool = Find-SignTool
Write-Host "Using signtool: $signtool"
Write-Host "Signing: $ExePath"

& $signtool sign `
  /f $PfxPath `
  /p $Password `
  /fd sha256 `
  /tr $TimestampUrl `
  /td sha256 `
  /d "Nexuz" `
  $ExePath

if ($LASTEXITCODE -ne 0) {
  Write-Host "Timestamped sign failed (exit $LASTEXITCODE); retry without timestamp..."
  & $signtool sign `
    /f $PfxPath `
    /p $Password `
    /fd sha256 `
    /d "Nexuz" `
    $ExePath
  if ($LASTEXITCODE -ne 0) {
    throw "signtool failed with exit $LASTEXITCODE"
  }
}

Assert-HasAuthenticodeSignature -Path $ExePath
Write-Host "OK: signed $ExePath"
