# META NUKE

Forensically-safe offline metadata stripper. Removes ALL metadata (EXIF, GPS, ICC, timestamps) by reconstructing images from raw pixel data. Built for privacy scenarios where forensic analysis must find nothing.

## Commands

```bash
meta-nuke --help                         # CLI (pip-installed)
python -m metanuke.cli --help            # Module
python meta_nuke.py --help               # Legacy shim
./run.sh                                 # GUI runner
./setup.sh                               # First-time setup (venv + deps)
```

## Supported formats

JPG, JPEG, PNG, GIF, BMP, TIFF, TIF, WEBP, SVG, AVIF, HEIC, HEIF, PDF

## Security invariants (non-negotiable)

1. **100% offline** — no network access, ever
2. **Complete metadata destruction** — strip everything, not sanitize
3. **Pixel-only reconstruction** — rebuild from raw pixels, not file structure
4. **No metadata in output** — `clean_image.info` must be `{}`
5. **Binary-level verification** — scan raw bytes, not just PIL metadata
6. **Forensic countermeasures** — noise injection, double-encoding, timestamp reset are critical
7. **File overwrite** — original overwritten via atomic buffer operation

## Architecture

Package: `metanuke/` with four modules:

- `core.py` — `MetaNuke` engine (pixel reconstruction, binary stripping, verification)
- `gui.py` — `MetaNukeGUI` (Tkinter UI with drag-and-drop, noise slider, preview)
- `cli.py` — `main()` entry point with argparse
- `utils.py` — banner, config persistence, audit log, file collection, preview helpers

Four-layer approach: pixel reconstruction → format-specific binary stripping → forensic countermeasures → structural verification.

## Dependencies

- Pillow (>=10.0.0)
- pillow-heif (optional, HEIC/HEIF)
- PyMuPDF (optional, PDF)
- tqdm (optional, progress bars)
- tkinterdnd2 (optional, drag-and-drop)

Full reference: `REFERENCE.md`
