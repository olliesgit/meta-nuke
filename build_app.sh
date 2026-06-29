#!/bin/bash
# Build a fully standalone "Meta Nuke.app" with PyInstaller.
#
# Unlike the lightweight launcher bundle (which shells out to the vault venv),
# this produces a portable .app you can copy to /Applications or hand to anyone
# — no Python, pyenv, or venv required on the target machine. It also bundles a
# matching tkdnd, so drag-and-drop works regardless of the host's Tcl/Tk.
set -euo pipefail

cd "$(dirname "$0")"

# Prefer the project venv interpreter directly. Using the absolute path avoids
# wrappers/aliases (e.g. uv) that can shadow `python` and target a different env.
if [ -x "venv/bin/python" ]; then
    PYTHON="$(pwd)/venv/bin/python"
elif [ -x ".venv/bin/python" ]; then
    PYTHON="$(pwd)/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi

echo "==> Ensuring build dependencies (PyInstaller + all optional features)…"
$PYTHON -m pip install --quiet --upgrade pyinstaller
# tkinterdnd2 pinned <0.5: 0.5.0 dropped the arm64 + Tcl 8.6 tkdnd binary
# (ships Tcl 9 only), breaking drag-and-drop on Apple Silicon.
$PYTHON -m pip install --quiet pillow pillow-heif PyMuPDF "tkinterdnd2>=0.4.2,<0.5" numpy

echo "==> Cleaning previous build…"
rm -rf build "dist/Meta Nuke.app"

echo "==> Building…"
$PYTHON -m PyInstaller --noconfirm MetaNuke.spec

echo
echo "==> Done: dist/Meta Nuke.app"
echo "    Install with:  cp -R 'dist/Meta Nuke.app' /Applications/"
