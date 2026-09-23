#!/usr/bin/env bash
# QMD Personal Knowledgebase — 1-Click Installer for macOS & Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================================================"
echo "   QMD Personal Knowledgebase and Search Engine — 1-Click Setup"
echo "======================================================================"
echo ""

# 1. Check Python
echo "[*] Checking Python runtime..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3.10+ is required but not installed."
    exit 1
fi

$PYTHON_CMD -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || {
    echo "[ERROR] Python 3.10+ required. Please upgrade your Python version."
    exit 1
}
echo "[OK] Python detected: $($PYTHON_CMD --version)"

# 2. Initialize directories
echo "[*] Initializing local directories..."
mkdir -p "$SCRIPT_DIR/corpus" "$SCRIPT_DIR/inbox" "$SCRIPT_DIR/logs"

# 3. Initialize .env if missing
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "[*] Generating default .env..."
    cat << 'EOF' > "$SCRIPT_DIR/.env"
# QMD Personal Knowledgebase Local Configuration
OPERATIONAL_MODE=full
QMD_PORT=8181
AUTH_PROXY_PORT=3210
CONTROL_PLANE_PORT=3333
EOF
    echo "[OK] Generated .env file."
fi

# 4. Install dependencies
echo "[*] Installing Python dependencies..."
$PYTHON_CMD -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt" || {
    echo "[WARNING] Non-critical dependencies skipped."
}

# 5. Make launcher executable
chmod +x "$SCRIPT_DIR/scripts/run_desktop.py"

echo ""
echo "======================================================================"
echo "   Installation Complete!"
echo "======================================================================"
echo "Run the knowledgebase with: python3 scripts/run_desktop.py"
echo ""
