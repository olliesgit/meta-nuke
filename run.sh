#!/bin/bash
# META NUKE Runner
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "First run detected. Setting up..."
    ./setup.sh
fi

source venv/bin/activate

# Install the package in development mode so 'from metanuke' imports work
if ! python -c "from metanuke import MetaNuke" 2>/dev/null; then
    pip install -e . --quiet
fi

python -m metanuke.cli "$@"
