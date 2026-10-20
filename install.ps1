# Sentinel Bootstrap Installer - Windows PowerShell
& {
    $ProgressPreference = "SilentlyContinue"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {}

    $RepoBase    = "https://raw.githubusercontent.com/TyronVDW/sentinel/main"
    $SentinelDir = "$env:USERPROFILE\.sentinel"
    $BinDir      = "$env:USERPROFILE\.local\bin"

    Write-Host "=== Sentinel ===" -ForegroundColor Cyan

    New-Item -ItemType Directory -Force -Path $SentinelDir, $BinDir | Out-Null

    try {
        Invoke-WebRequest "$RepoBase/relay.py" -OutFile "$SentinelDir\relay.py" -UseBasicParsing
    } catch {
        Write-Host "Could not download Sentinel: $($_.Exception.Message)" -ForegroundColor Red
        return
    }

    # uv: one standalone binary that brings its own Python.
    # No system Python, no Microsoft Store stub, no admin rights.
    $env:Path = "$BinDir;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "Setting up runtime (one-time)..." -ForegroundColor Yellow
        # Child process with ExecutionPolicy ByPass: uv's installer refuses to run under
        # the default 'Restricted' policy, and runs in its own process so it can't close this window.
        powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        $env:Path = "$BinDir;$env:USERPROFILE\.cargo\bin;$env:Path"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "Runtime setup failed: uv was not found after install." -ForegroundColor Red
        return
    }

    # 'sentinel' command for next time (CRLF line endings so cmd.exe is happy)
    $Launcher = @(
        '@echo off',
        'set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"',
        'uv run --script "%USERPROFILE%\.sentinel\relay.py" %*'
    ) -join "`r`n"
    Set-Content -Path "$BinDir\sentinel.bat" -Value $Launcher -Encoding ASCII

    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    if ($UserPath -notlike "*$BinDir*") {
        $NewPath = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
        [System.Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    }

    Write-Host "Done. Starting Sentinel..." -ForegroundColor Green
    Write-Host ""
    uv run --script "$SentinelDir\relay.py"
}
