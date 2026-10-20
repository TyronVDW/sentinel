#!/bin/sh
# Sentinel Bootstrap Installer — Unix / Linux / macOS / iOS iSH
set -e

REPO_BASE="https://raw.githubusercontent.com/TyronVDW/sentinel/main"
SENTINEL_DIR="$HOME/.sentinel"
BIN_DIR="$HOME/.local/bin"
OS=$(uname -s)

echo "=== Sentinel ==="

mkdir -p "$SENTINEL_DIR" "$BIN_DIR"
curl -sSL "$REPO_BASE/relay.py" -o "$SENTINEL_DIR/relay.py"

if [ "$OS" = "Darwin" ]; then
    # Try the system Python first — works fine on machines where it's already set up.
    if command -v python3 >/dev/null 2>&1 \
       && python3 -m pip install --user --quiet --prefer-binary anthropic >/dev/null 2>&1; then
        cat > "$BIN_DIR/sentinel" << EOF
#!/bin/sh
exec python3 "$SENTINEL_DIR/relay.py" "\$@"
EOF
    else
        # System Python is unusable (e.g. Xcode license not accepted) — use uv instead.
        # uv is a static binary: no compiler, no Xcode, just a download.
        if ! command -v uv >/dev/null 2>&1; then
            curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
        fi
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        cat > "$BIN_DIR/sentinel" << EOF
#!/bin/sh
export PATH="\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH"
exec uv run --script "$SENTINEL_DIR/relay.py" "\$@"
EOF
    fi
else
    # Linux / iSH — no Xcode concerns here.
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Installing Python 3..."
        if   command -v apt-get >/dev/null 2>&1; then apt-get install -y python3 python3-pip
        elif command -v apk     >/dev/null 2>&1; then apk add python3 py3-pip
        elif command -v yum     >/dev/null 2>&1; then yum install -y python3 python3-pip
        else echo "Please install Python 3 manually."; exit 1
        fi
    fi
    python3 -m pip install --user --quiet --prefer-binary anthropic 2>/dev/null \
      || pip3 install --user --quiet --prefer-binary anthropic
    cat > "$BIN_DIR/sentinel" << EOF
#!/bin/sh
exec python3 "$SENTINEL_DIR/relay.py" "\$@"
EOF
fi
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

# Rebind stdin to the real terminal — this script's own stdin is the curl pipe,
# not the keyboard, so without this the password prompt gets no input.
if [ -t 1 ] && [ -r /dev/tty ]; then
    exec "$BIN_DIR/sentinel" < /dev/tty
else
    exec "$BIN_DIR/sentinel"
fi
