#!/bin/sh
# Sentinel Bootstrap Installer — Unix / Linux / macOS / iOS iSH
set -e

REPO_BASE="https://raw.githubusercontent.com/TyronVDW/sentinel/main"
SENTINEL_DIR="$HOME/.sentinel"

echo "=== Sentinel ==="

# ── Python 3 ──────────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo "Installing Python 3..."
    if   command -v apt-get >/dev/null 2>&1; then apt-get install -y python3 python3-pip
    elif command -v apk     >/dev/null 2>&1; then apk add python3 py3-pip
    elif command -v yum     >/dev/null 2>&1; then yum install -y python3 python3-pip
    elif command -v brew    >/dev/null 2>&1; then brew install python3
    else echo "Please install Python 3 manually."; exit 1
    fi
fi

# ── dependencies ──────────────────────────────────────────────────────────────
python3 -m pip install --user --quiet --prefer-binary anthropic 2>/dev/null \
  || pip3 install --user --quiet --prefer-binary anthropic \
  || { curl -sSL https://bootstrap.pypa.io/get-pip.py | python3 - --user --quiet; \
       python3 -m pip install --user --quiet --prefer-binary anthropic; }

# ── download relay ────────────────────────────────────────────────────────────
mkdir -p "$SENTINEL_DIR"
curl -sSL "$REPO_BASE/relay.py" -o "$SENTINEL_DIR/relay.py"

# ── sentinel command ──────────────────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/sentinel" << 'EOF'
#!/bin/sh
exec python3 "$HOME/.sentinel/relay.py" "$@"
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

echo "Done. Starting Sentinel..."
echo ""
exec python3 "$SENTINEL_DIR/relay.py"
