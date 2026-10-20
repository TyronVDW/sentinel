#!/bin/sh
# Sentinel Bootstrap Installer — Unix / Linux / macOS / iOS iSH
set -e

REPO_BASE="https://raw.githubusercontent.com/YOUR_GITHUB/sentinel/main"
SENTINEL_DIR="$HOME/.sentinel"

echo "=== Sentinel Installer ==="
OS=$(uname -s)
echo "OS: $OS"

# ── Python 3 ──────────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo "Installing Python 3..."
    if   command -v apt-get >/dev/null 2>&1; then apt-get install -y python3 python3-pip
    elif command -v apk     >/dev/null 2>&1; then apk add python3 py3-pip
    elif command -v yum     >/dev/null 2>&1; then yum install -y python3 python3-pip
    elif command -v brew    >/dev/null 2>&1; then brew install python3
    else echo "Cannot install Python 3 automatically. Please install it manually."; exit 1
    fi
fi
echo "Python: $(python3 --version)"

# ── anthropic SDK ─────────────────────────────────────────────────────────────
echo "Installing Anthropic SDK..."
python3 -m pip install --user --quiet anthropic 2>/dev/null \
  || pip3 install --user --quiet anthropic

# ── files ─────────────────────────────────────────────────────────────────────
mkdir -p "$SENTINEL_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo ".")"
if [ -f "$SCRIPT_DIR/relay.py" ] && [ -f "$SCRIPT_DIR/config.json" ]; then
    cp "$SCRIPT_DIR/relay.py"   "$SENTINEL_DIR/relay.py"
    cp "$SCRIPT_DIR/config.json" "$SENTINEL_DIR/config.json"
    echo "Files copied from local directory."
else
    echo "Downloading from GitHub..."
    curl -sSL "$REPO_BASE/relay.py"    -o "$SENTINEL_DIR/relay.py"
    curl -sSL "$REPO_BASE/config.json" -o "$SENTINEL_DIR/config.json"
fi

# ── API key ───────────────────────────────────────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ]; then
    printf "\nEnter your Anthropic API key: "
    read -r API_KEY

    # Find shell profile
    for PROFILE in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
        if [ -f "$PROFILE" ]; then
            SHELL_PROFILE="$PROFILE"
            break
        fi
    done

    if [ -n "$SHELL_PROFILE" ]; then
        printf '\nexport ANTHROPIC_API_KEY="%s"\n' "$API_KEY" >> "$SHELL_PROFILE"
        echo "API key saved to $SHELL_PROFILE"
    fi
    export ANTHROPIC_API_KEY="$API_KEY"
fi

# ── sentinel command ──────────────────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
SENTINEL_CMD="$BIN_DIR/sentinel"

cat > "$SENTINEL_CMD" << 'SENTINEL_EOF'
#!/bin/sh
exec python3 "$HOME/.sentinel/relay.py" "$@"
SENTINEL_EOF
chmod +x "$SENTINEL_CMD"

# Ensure PATH
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        [ -n "$SHELL_PROFILE" ] && printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$SHELL_PROFILE"
        export PATH="$BIN_DIR:$PATH"
        ;;
esac

echo ""
echo "=== Installation complete ==="
echo "Run: sentinel"
echo ""
exec "$SENTINEL_CMD"
