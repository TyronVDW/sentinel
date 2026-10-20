# Sentinel Bootstrap Installer — Windows PowerShell
$ErrorActionPreference = "Stop"
$RepoBase   = "https://raw.githubusercontent.com/YOUR_GITHUB/sentinel/main"
$SentinelDir = "$env:USERPROFILE\.sentinel"

Write-Host "=== Sentinel Installer ===" -ForegroundColor Cyan

# ── Python 3 ──────────────────────────────────────────────────────────────────
$PyCmd = $null
foreach ($c in @("python3","python")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
        $v = & $c --version 2>&1
        if ($v -match "Python 3") { $PyCmd = $c; break }
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
Write-Host "Python: $(& $PyCmd --version)" -ForegroundColor Green

# ── anthropic SDK ─────────────────────────────────────────────────────────────
Write-Host "Installing Anthropic SDK..."
& $PyCmd -m pip install --user --quiet anthropic

# ── files ─────────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $SentinelDir | Out-Null

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path "$ScriptDir\relay.py") {
    Copy-Item "$ScriptDir\relay.py"    "$SentinelDir\relay.py"
    Copy-Item "$ScriptDir\config.json" "$SentinelDir\config.json"
    Write-Host "Files copied from local directory."
} else {
    Write-Host "Downloading from GitHub..."
    Invoke-WebRequest "$RepoBase/relay.py"    -OutFile "$SentinelDir\relay.py"
    Invoke-WebRequest "$RepoBase/config.json" -OutFile "$SentinelDir\config.json"
}

# ── API key ───────────────────────────────────────────────────────────────────
if (-not $env:ANTHROPIC_API_KEY) {
    $Key = Read-Host "Enter your Anthropic API key"
    [System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $Key, "User")
    $env:ANTHROPIC_API_KEY = $Key
    Write-Host "API key saved to user environment." -ForegroundColor Green
}

# ── sentinel command ──────────────────────────────────────────────────────────
$BinDir = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

$BatPath = "$BinDir\sentinel.bat"
@"
@echo off
$PyCmd "%USERPROFILE%\.sentinel\relay.py" %*
"@ | Out-File -FilePath $BatPath -Encoding ASCII

$UserPath = [System.Environment]::GetEnvironmentVariable("Path","User")
if ($UserPath -notlike "*$BinDir*") {
    [System.Environment]::SetEnvironmentVariable("Path","$UserPath;$BinDir","User")
    $env:Path += ";$BinDir"
}

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host "Run: sentinel"
Write-Host ""
& $PyCmd "$SentinelDir\relay.py"
