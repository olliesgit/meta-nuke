#!/bin/bash
# META NUKE Runner
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "First run detected. Setting up..."
    ./setup.sh
fi

source venv/bin/activate
python meta_nuke.py "$@"

