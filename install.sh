#!/bin/sh
# Sentinel Bootstrap Installer - Unix / Linux / macOS / iOS iSH
# Installs Sentinel as a background service that starts on boot/login and
# restarts itself if it stops. One-liner:
#   curl -fsSL https://raw.githubusercontent.com/TyronVDW/sentinel/main/install.sh | sh
set -e

REPO_BASE="https://raw.githubusercontent.com/TyronVDW/sentinel/main"
SENTINEL_DIR="$HOME/.sentinel"
BIN_DIR="$HOME/.local/bin"
OS=$(uname -s)

echo "=== Sentinel ==="
mkdir -p "$SENTINEL_DIR" "$BIN_DIR"
curl -sSL "$REPO_BASE/relay.py" -o "$SENTINEL_DIR/relay.py"

# ── runtime ──────────────────────────────────────────────────────────────────
RUN_CMD=""
if [ "$OS" = "Darwin" ]; then
    if command -v python3 >/dev/null 2>&1 \
       && python3 -m pip install --user --quiet --prefer-binary anthropic websocket-client >/dev/null 2>&1; then
        RUN_CMD="python3 \"$SENTINEL_DIR/relay.py\""
    else
        if ! command -v uv >/dev/null 2>&1; then
            curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
        fi
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        RUN_CMD="uv run --script \"$SENTINEL_DIR/relay.py\""
    fi
else
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Installing Python 3..."
        if   command -v apt-get >/dev/null 2>&1; then apt-get install -y python3 python3-pip
        elif command -v apk     >/dev/null 2>&1; then apk add python3 py3-pip
        elif command -v yum     >/dev/null 2>&1; then yum install -y python3 python3-pip
        else echo "Please install Python 3 manually."; exit 1
        fi
    fi
    python3 -m pip install --user --quiet --prefer-binary anthropic websocket-client 2>/dev/null \
      || pip3 install --user --quiet --prefer-binary anthropic websocket-client
    RUN_CMD="python3 \"$SENTINEL_DIR/relay.py\""
fi

# ── password (stored so the service starts unattended) ───────────────────────
if [ -z "$SENTINEL_PASSWORD" ] && [ ! -f "$SENTINEL_DIR/env" ]; then
    printf "Sentinel password: " > /dev/tty
    stty -echo < /dev/tty 2>/dev/null || true
    read SENTINEL_PASSWORD < /dev/tty
    stty echo < /dev/tty 2>/dev/null || true
    echo "" > /dev/tty
fi
if [ -n "$SENTINEL_PASSWORD" ]; then
    umask 077
    printf 'SENTINEL_PASSWORD=%s\n' "$SENTINEL_PASSWORD" > "$SENTINEL_DIR/env"
    chmod 600 "$SENTINEL_DIR/env"
fi

# ── launcher ─────────────────────────────────────────────────────────────────
cat > "$BIN_DIR/sentinel" << EOF
#!/bin/sh
export PATH="\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH"
[ -f "$SENTINEL_DIR/env" ] && . "$SENTINEL_DIR/env" && export SENTINEL_PASSWORD
exec $RUN_CMD "\$@"
EOF
chmod +x "$BIN_DIR/sentinel"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        for PROFILE in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
            if [ -f "$PROFILE" ]; then
                printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$PROFILE"
                break
            fi
        done
        export PATH="$BIN_DIR:$PATH"
        ;;
esac

# ── background service + autostart ───────────────────────────────────────────
set +e
installed_service=0

if [ "$OS" = "Darwin" ]; then
    # macOS: launchd LaunchAgent (starts at login, KeepAlive restarts on exit)
    PLIST="$HOME/Library/LaunchAgents/com.sentinel.relay.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sentinel.relay</string>
  <key>ProgramArguments</key><array><string>$BIN_DIR/sentinel</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$SENTINEL_DIR/service.log</string>
  <key>StandardErrorPath</key><string>$SENTINEL_DIR/service.log</string>
</dict></plist>
EOF
    launchctl unload "$PLIST" 2>/dev/null
    launchctl load "$PLIST" 2>/dev/null && installed_service=1

elif command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    # Linux with systemd: user service (enable linger so it runs without login)
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/sentinel.service" << EOF
[Unit]
Description=Sentinel Relay
After=network-online.target

[Service]
ExecStart=$BIN_DIR/sentinel
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload 2>/dev/null
    systemctl --user enable --now sentinel.service 2>/dev/null && installed_service=1
    command -v loginctl >/dev/null 2>&1 && loginctl enable-linger "$(whoami)" 2>/dev/null
fi

if [ "$installed_service" = "1" ]; then
    echo ""
    echo "Done. Sentinel is running in the background (starts on boot/login, auto-restarts)."
    echo "It should appear in your hub dashboard within ~20s."
else
    # No service manager (e.g. iSH on iOS): background it now + @reboot cron.
    echo ""
    echo "No service manager found - starting in the background."
    nohup "$BIN_DIR/sentinel" > "$SENTINEL_DIR/service.log" 2>&1 &
    if command -v crontab >/dev/null 2>&1; then
        ( crontab -l 2>/dev/null | grep -v "\.sentinel.*relay"; \
          echo "@reboot $BIN_DIR/sentinel > $SENTINEL_DIR/service.log 2>&1" ) | crontab - 2>/dev/null
    fi
    echo "Sentinel started. (On iOS/iSH it runs only while the app stays open.)"
fi
