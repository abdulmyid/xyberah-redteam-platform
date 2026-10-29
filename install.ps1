# Xyberah one-command installer (Windows / PowerShell).
# Usage:  .\install.ps1
$ErrorActionPreference = "Stop"

Write-Host "`n=== Xyberah installer ===" -ForegroundColor Cyan

try { docker version | Out-Null } catch {
  Write-Host "Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red; exit 1
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  # Generate a strong random admin password
  $bytes = New-Object byte[] 18
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $pw = [Convert]::ToBase64String($bytes) -replace '[/+=]', 'x'
  (Get-Content ".env") -replace '^XYBERAH_ADMIN_PASSWORD=.*', "XYBERAH_ADMIN_PASSWORD=$pw" |
    Set-Content ".env" -Encoding utf8
  Write-Host "Created .env with a generated admin password." -ForegroundColor Green
  $script:generatedPw = $pw
} else {
  Write-Host ".env already exists; leaving it unchanged." -ForegroundColor Yellow
}

Write-Host "`nBuilding and starting containers (first build downloads the scanners, ~15 min)..." -ForegroundColor Cyan
docker compose up -d --build

$port = (Select-String -Path ".env" -Pattern '^XYBERAH_HTTPS_PORT=(.*)').Matches.Groups[1].Value
if (-not $port) { $port = "8443" }

Write-Host "`n=== Xyberah is starting ===" -ForegroundColor Green
Write-Host "URL:      https://localhost:$port"
Write-Host "Username: $((Select-String -Path '.env' -Pattern '^XYBERAH_ADMIN_USERNAME=(.*)').Matches.Groups[1].Value)"
if ($script:generatedPw) {
  Write-Host "Password: $($script:generatedPw)" -ForegroundColor Yellow
  Write-Host "(also saved in .env — change it after first login)"
} else {
  Write-Host "Password: (see XYBERAH_ADMIN_PASSWORD in .env)"
}
Write-Host "`nThe certificate is self-signed, so your browser will warn once. Continue past it,"
Write-Host "or upload your own certificate under Settings -> TLS certificate."
Write-Host "`nLogs:  docker compose logs -f backend"
