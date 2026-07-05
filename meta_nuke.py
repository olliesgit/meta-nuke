#!/usr/bin/env python3
"""Meta Nuke — Forensically-safe offline metadata stripper.

Nuclear-grade metadata removal. Completely reconstructs images from raw pixels.
NO metadata survives. NO exceptions. 100% local, 100% offline.

For details: https://github.com/olliesgit/meta-nuke
"""

import multiprocessing
import sys
from pathlib import Path

# Allow running directly from the repo root
repo_root = Path(__file__).resolve().parent
if (repo_root / 'metanuke').is_dir():
    sys.path.insert(0, str(repo_root))

from metanuke.cli import main

if __name__ == "__main__":
    # In a frozen (PyInstaller) build, a child process spawned via
    # multiprocessing re-executes this app with interpreter flags
    # (-B -S -I -c ...). Without this guard those flags leak into argv and
    # argparse aborts. Must run before any other work.
    multiprocessing.freeze_support()
    main()
