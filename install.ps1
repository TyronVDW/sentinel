# Sentinel Bootstrap Installer - Windows PowerShell
# Installs Sentinel as a hidden background service that starts at logon and
# restarts itself if it stops. One-liner:
#   irm https://raw.githubusercontent.com/TyronVDW/sentinel/main/install.ps1 | iex
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

    # uv: one standalone binary that brings its own Python. No system Python,
    # no Microsoft Store stub, no admin rights.
    $env:Path = "$BinDir;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "Setting up runtime (one-time)..." -ForegroundColor Yellow
        powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        $env:Path = "$BinDir;$env:USERPROFILE\.cargo\bin;$env:Path"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "Runtime setup failed: uv was not found after install." -ForegroundColor Red
        return
    }

    # Password: stored in the user environment so the background service can
    # start unattended. The relay reads SENTINEL_PASSWORD from the environment.
    $existing = [System.Environment]::GetEnvironmentVariable("SENTINEL_PASSWORD", "User")
    if (-not $existing) {
        $sec  = Read-Host "Sentinel password" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        $pw   = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        [System.Environment]::SetEnvironmentVariable("SENTINEL_PASSWORD", $pw, "User")
        $env:SENTINEL_PASSWORD = $pw
    }

    # Hidden launcher: sets PATH and runs the relay with no console window.
    @'
@echo off
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
uv run --script "%USERPROFILE%\.sentinel\relay.py"
'@ | Set-Content "$SentinelDir\sentinel-run.cmd" -Encoding ASCII

    @'
CreateObject("WScript.Shell").Run "cmd /c ""%USERPROFILE%\.sentinel\sentinel-run.cmd""", 0, False
'@ | Set-Content "$SentinelDir\sentinel-hidden.vbs" -Encoding ASCII

    # 'sentinel' command for manual/interactive runs.
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

    # Background service: scheduled task at logon, hidden, auto-restart.
    $action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$SentinelDir\sentinel-hidden.vbs`""
    $trigger  = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    try {
        Register-ScheduledTask -TaskName "Sentinel" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName "Sentinel"
        Write-Host "Done. Sentinel is running in the background (starts at login, auto-restarts)." -ForegroundColor Green
        Write-Host "It should appear in your hub dashboard within ~20s." -ForegroundColor Green
    } catch {
        Write-Host "Could not register the background task ($($_.Exception.Message))." -ForegroundColor Yellow
        Write-Host "Re-run this in an Administrator PowerShell, or starting in this window for now..." -ForegroundColor Yellow
        uv run --script "$SentinelDir\relay.py"
    }
}
