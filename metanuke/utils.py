"""Utility functions for Meta Nuke — CLI helpers, config, logging, preview."""

import json
import os
from datetime import datetime
from pathlib import Path

from PIL import Image

from metanuke.core import MetaNuke


BANNER = r"""
███╗   ███╗███████╗████████╗ █████╗     ███╗   ██╗██╗   ██╗██╗  ██╗███████╗
████╗ ████║██╔════╝╚══██╔══╝██╔══██╗    ████╗  ██║██║   ██║██║ ██╔╝██╔════╝
██╔████╔██║█████╗     ██║   ███████║    ██╔██╗ ██║██║   ██║█████╔╝ █████╗
██║╚██╔╝██║██╔══╝     ██║   ██╔══██║    ██║╚██╗██║██║   ██║██╔═██╗ ██╔══╝
██║ ╚═╝ ██║███████╗   ██║   ██║  ██║    ██║ ╚████║╚██████╔╝██║  ██╗███████╗
╚═╝     ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝    ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝
"""


def print_banner():
    """Print the ASCII art logo."""
    print(BANNER)
    print("Forensically-safe offline metadata stripper")
    print("100% local  ·  100% offline  ·  Zero traces left")
    print()


def show_preview(file_path: str):
    """Show metadata found in an image before nuking."""
    path = Path(file_path)
    print(f"\n  {path.name}:")
    has_meta = False
    try:
        with Image.open(file_path) as img:
            info = img.info
            if info:
                has_meta = True
                for k, v in info.items():
                    val = str(v)[:80]
                    print(f"    {k}: {val}")
            else:
                print("    (no metadata found — already clean)")
    except Exception as e:
        print(f"    (cannot read: {e})")
    raw = path.read_bytes()
    markers = {
        b'Exif\x00\x00': 'EXIF header',
        b'<x:xmpmeta': 'XMP metadata',
        b'ICC_PROFILE': 'ICC profile',
        b'Photoshop': 'Photoshop data',
    }
    found = [name for sig, name in markers.items() if sig in raw]
    if found:
        has_meta = True
        print(f"    binary markers: {', '.join(found)}")
    if not has_meta:
        print(f"    ✓ Clean — no metadata detected")


def show_preview_collect(files: list[str]):
    """Preview mode: show metadata for all files without nuking."""
    for f in files:
        show_preview(f)
    print()


def collect_files(paths, recursive=False):
    """Collect all supported image files from paths (files or directories).

    Deduplicates so the same file passed twice (e.g. via FILE + --dir, or an
    overlapping directory) is only processed once.
    """
    files = []
    for p in paths:
        p = Path(p)
        if p.is_file():
            if p.suffix.lower() in MetaNuke.SUPPORTED_FORMATS:
                files.append(str(p))
        elif p.is_dir():
            glob = '**/*' if recursive else '*'
            for f in sorted(p.glob(glob)):
                if f.is_file() and f.suffix.lower() in MetaNuke.SUPPORTED_FORMATS:
                    files.append(str(f))
    # dict.fromkeys preserves order and drops duplicates.
    return list(dict.fromkeys(files))


def log_results(log_path: str, results: list):
    """Append audit log entry."""
    timestamp = datetime.now().isoformat(timespec='seconds')
    lines = [f"--- {timestamp} ---"]
    ok = sum(1 for _, s, _ in results if s)
    bad = len(results) - ok
    lines.append(f"total={len(results)} ok={ok} failed={bad}")
    for path, success, msg in results:
        status = "OK" if success else "FAIL"
        lines.append(f"  {status} {path}")
    lines.append("")
    with open(log_path, 'a') as f:
        f.write('\n'.join(lines) + '\n')


def load_config(path: str = None) -> dict:
    """Load user config from ~/.metanukerc (JSON)."""
    if path is None:
        path = os.path.join(os.path.expanduser('~'), '.metanukerc')
    defaults = {'noise_level': 5, 'output_dir': None, 'audit_log': False}
    if not os.path.exists(path):
        return defaults
    try:
        with open(path) as f:
            cfg = json.load(f)
        for k in defaults:
            cfg.setdefault(k, defaults[k])
        return cfg
    except Exception:
        return defaults


def save_config(cfg: dict, path: str = None):
    """Save user config to ~/.metanukerc (JSON)."""
    if path is None:
        path = os.path.join(os.path.expanduser('~'), '.metanukerc')
    try:
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
