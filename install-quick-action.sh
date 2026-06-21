#!/bin/bash
# Install Meta Nuke Quick Action for macOS Finder
# After running this, right-click any image in Finder → Quick Actions → "Nuke with MetaNuke"

set -e

WORKFLOW_DIR="$HOME/Library/Services"
WORKFLOW_NAME="Nuke with MetaNuke.workflow"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)/MetaNuke.workflow"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "❌ MetaNuke.workflow not found in $SOURCE_DIR"
    echo "   Run this script from the meta-nuke project directory."
    exit 1
fi

# Remove old version if exists
if [ -d "$WORKFLOW_DIR/$WORKFLOW_NAME" ]; then
    echo "→ Removing previous installation..."
    rm -rf "$WORKFLOW_DIR/$WORKFLOW_NAME"
fi

# Copy workflow
echo "→ Installing Quick Action..."
cp -R "$SOURCE_DIR" "$WORKFLOW_DIR/$WORKFLOW_NAME"

echo "✅ Installed to: $WORKFLOW_DIR/$WORKFLOW_NAME"
echo ""
echo "To use it:"
echo "  1. Right-click an image file in Finder"
echo "  2. Choose Quick Actions → Nuke with MetaNuke"
echo ""
echo "Or set it up:"
echo "  System Settings → Privacy & Security → Extensions → Finder"
echo "  → Enable \"Nuke with MetaNuke\""
echo ""
echo "If you see a security warning on first use:"
echo "  System Settings → Privacy & Security → run anyway"
