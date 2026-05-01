#!/usr/bin/env bash
set -euo pipefail

echo "Building oasis binary..."
pyinstaller \
  --onefile \
  --name oasis \
  --clean \
  --noconfirm \
  src/oasis/main.py

echo ""
echo "Build complete: dist/oasis"
echo ""
echo "To install for your partner:"
echo "  cp dist/oasis /usr/local/bin/oasis"
echo "  oasis setup"
