# Sentinel Bootstrap Installer — Windows PowerShell
$RepoBase    = "https://raw.githubusercontent.com/TyronVDW/sentinel/main"
$SentinelDir = "$env:USERPROFILE\.sentinel"
$BinDir      = "$env:USERPROFILE\.local\bin"

Write-Host "=== Sentinel ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $SentinelDir, $BinDir | Out-Null
Invoke-WebRequest "$RepoBase/relay.py" -OutFile "$SentinelDir\relay.py" -UseBasicParsing

# ── uv: standalone runner, brings its own Python (no Store stub, no MSI, no admin) ──
$env:Path = "$BinDir;$env:USERPROFILE\.cargo\bin;$env:Path"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Setting up runtime..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$BinDir;$env:USERPROFILE\.cargo\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Runtime setup failed: uv not found after install." -ForegroundColor Red
    return
}

# ── sentinel command ──────────────────────────────────────────────────────────
@"
@echo off
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
uv run --script "%USERPROFILE%\.sentinel\relay.py" %*
"@ | Out-File -FilePath "$BinDir\sentinel.bat" -Encoding ASCII

$UserPath = [System.Environment]::GetEnvironmentVariable("Path","User")
if ($UserPath -notlike "*$BinDir*") {
    [System.Environment]::SetEnvironmentVariable("Path","$UserPath;$BinDir","User")
}

Write-Host "Done. Starting Sentinel..." -ForegroundColor Green
Write-Host ""
uv run --script "$SentinelDir\relay.py"
