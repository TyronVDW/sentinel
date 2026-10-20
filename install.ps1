# Sentinel Bootstrap Installer — Windows PowerShell
$ErrorActionPreference = "Stop"
$RepoBase    = "https://raw.githubusercontent.com/TyronVDW/sentinel/main"
$SentinelDir = "$env:USERPROFILE\.sentinel"

Write-Host "=== Sentinel ===" -ForegroundColor Cyan

# ── Python 3 ──────────────────────────────────────────────────────────────────
$PyCmd = $null
foreach ($c in @("python3","python")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
        if ((& $c --version 2>&1) -match "Python 3") { $PyCmd = $c; break }
    }
}
if (-not $PyCmd) {
    Write-Host "Downloading Python 3.11..." -ForegroundColor Yellow
    $ins = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe" -OutFile $ins
    Start-Process $ins "/quiet InstallAllUsers=0 PrependPath=1" -Wait
    Remove-Item $ins
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","Machine")
    $PyCmd = "python"
}

# ── dependencies ──────────────────────────────────────────────────────────────
Write-Host "Installing dependencies..."
& $PyCmd -m pip install --user --quiet anthropic

# ── download relay ────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $SentinelDir | Out-Null
Invoke-WebRequest "$RepoBase/relay.py" -OutFile "$SentinelDir\relay.py"

# ── sentinel command ──────────────────────────────────────────────────────────
$BinDir = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
"@echo off`r`n$PyCmd `"%USERPROFILE%\.sentinel\relay.py`" %*" | Out-File -FilePath "$BinDir\sentinel.bat" -Encoding ASCII

$UserPath = [System.Environment]::GetEnvironmentVariable("Path","User")
if ($UserPath -notlike "*$BinDir*") {
    [System.Environment]::SetEnvironmentVariable("Path","$UserPath;$BinDir","User")
    $env:Path += ";$BinDir"
}

Write-Host "Done. Starting Sentinel..." -ForegroundColor Green
Write-Host ""
& $PyCmd "$SentinelDir\relay.py"
