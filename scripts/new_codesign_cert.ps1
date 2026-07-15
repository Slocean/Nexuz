# Create a self-signed code-signing certificate for Nexuz (dev / interim).
# NOTE: Self-signed does NOT fully stop SmartScreen/Defender; for production buy an OV/EV cert.
#
# Usage:
#   .\scripts\new_codesign_cert.ps1
#   .\scripts\new_codesign_cert.ps1 -Password "YourStrongPass"
#
# Then add GitHub Secrets:
#   WINDOWS_CERTIFICATE          = base64 of the .pfx (one line)
#   WINDOWS_CERTIFICATE_PASSWORD = the password below

param(
  [string]$OutDir = ".codesign",
  [string]$Password = "",
  [string]$Subject = "CN=Nexuz, O=Nexuz, C=CN"
)

$ErrorActionPreference = "Stop"

if (-not $Password) {
  $Password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 | ForEach-Object { [char]$_ })
  Write-Host "Generated password (save it): $Password"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$pfxPath = Join-Path $OutDir "nexuz-codesign.pfx"
$cerPath = Join-Path $OutDir "nexuz-codesign.cer"
$b64Path = Join-Path $OutDir "nexuz-codesign.pfx.b64.txt"

$secure = ConvertTo-SecureString -String $Password -Force -AsPlainText
$cert = New-SelfSignedCertificate `
  -Type CodeSigningCert `
  -Subject $Subject `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyExportPolicy Exportable `
  -KeySpec Signature `
  -HashAlgorithm SHA256 `
  -NotAfter (Get-Date).AddYears(5)

Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure | Out-Null
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null

$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path $pfxPath))
$b64 = [Convert]::ToBase64String($bytes)
Set-Content -Path $b64Path -Value $b64 -NoNewline -Encoding ascii

Write-Host ""
Write-Host "OK: created"
Write-Host "  PFX:  $pfxPath"
Write-Host "  CER:  $cerPath"
Write-Host "  B64:  $b64Path"
Write-Host "  Pass: $Password"
Write-Host ""
Write-Host "GitHub -> Settings -> Secrets -> Actions:"
Write-Host "  WINDOWS_CERTIFICATE          = content of $b64Path"
Write-Host "  WINDOWS_CERTIFICATE_PASSWORD = $Password"
Write-Host ""
Write-Host "Local sign:"
Write-Host "  .\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe -PfxPath $pfxPath -Password `"$Password`""
