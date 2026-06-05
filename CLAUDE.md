# META NUKE

Forensically-safe offline metadata stripper. Removes ALL metadata (EXIF, GPS, ICC, timestamps) by reconstructing images from raw pixel data. Built for privacy scenarios where forensic analysis must find nothing.

## Commands

```bash
open "Meta Nuke.app"                    # macOS app
./run.sh                                # GUI
./run.sh /path/to/image.jpg             # Process file
./setup.sh                              # First-time setup (venv + deps)
```

## Supported formats

JPG, JPEG, PNG, GIF, BMP, TIFF, TIF, WEBP

## Security invariants (non-negotiable)

1. **100% offline** — no network access, ever
2. **Complete metadata destruction** — strip everything, not sanitize
3. **Pixel-only reconstruction** — rebuild from raw pixels, not file structure
4. **No metadata in output** — `clean_image.info` must be `{}`
5. **Binary-level verification** — scan raw bytes, not just PIL metadata
6. **Forensic countermeasures** — noise injection, double-encoding, timestamp reset are critical
7. **File overwrite** — original overwritten via atomic buffer operation

## Architecture

Single file: `meta_nuke.py`. Two classes: `MetaNuke` (engine) and `MetaNukeGUI` (Tkinter UI with drag-and-drop).

Four-layer approach: pixel reconstruction → format-specific binary stripping → forensic countermeasures → structural verification.

## Dependencies

- Pillow (>=10.0.0)
- tkinterdnd2 (>=0.3.0, optional for drag-and-drop)

Full reference: `REFERENCE.md`
