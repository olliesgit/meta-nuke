# Changelog

## [2026-06-05] — v1.1.0

### Added
- **AVIF format support** — Pillow 10+ handles it natively
- **PDF metadata stripping** — via PyMuPDF (fitz). Strips document metadata (author, creator, producer), XMP metadata, and re-encodes embedded images without their metadata
- **HEIC/HEIF support** — iPhone photos with GPS metadata now nukeable (pillow-heif)
- **SVG support** — XML-parses and strips `<metadata>`, `<desc>`, `<title>`, comments, processing instructions, and extra namespace declarations
- **Noise level control** — `--noise-level 0-10` (CLI) or slider in GUI. 0 = lossless, 5 = default, 10 = max
- **Output directory** — `--output DIR` / `-o DIR` (CLI) or BROWSE button in GUI. Saves to separate dir instead of overwriting in-place
- **Batch directory processing** — `--dir DIR` / `--recursive` (CLI). Drag-and-drop directories in GUI
- **Metadata preview** — `--preview` (CLI) or 🔍 PREVIEW button in GUI. Shows EXIF/XMP/ICC metadata without nuking
- **Audit log** — `--log FILE` (CLI) or AUDIT LOG checkbox in GUI. Appends timestamped results to a log file
- **SHA256 checksums** — shown in every success message. Verifiable file integrity
- **Progress bar** — tqdm for CLI bulk ops, Canvas-based progress bar widget in GUI
- **JSON output** — `--json` flag produces clean machine-readable output (no tqdm, no banner)
- **Config persistence** — `~/.metanukerc` saves noise level, output dir, and audit log preference between sessions
- **`--version` flag** — shows version and exits
- **`__version__`** — `"1.1.0"`

### Changed
- **CLI rewritten** with argparse — full `--help` with examples
- **GUI redesigned** — larger window (560x620), options panel with noise slider, output browser, preview, audit log
- **GUI progress** — visual fill-bar replaces text-only counter
- **GUI results** — SHA256 in results dialog, better summary
- **File browser** — dynamically builds file filter from SUPPORTED_FORMATS

### Fixed
- SVG output dir — creates parent directories automatically
- SVG namespace serialization — registers SVG namespace so tags render as `<rect>` not `<ns0:rect>`
- tqdm suppressed in JSON mode
- PDF saves to temp then renames (PyMuPDF limitation)

## [2026-06-02]

### Added
- `build_icon.py` — regenerates the macOS app icon from a 1024px master PNG: writes every required size to `MetaNuke.iconset/` and rebuilds `MetaNuke.icns` via `iconutil`. Run `venv/bin/python build_icon.py` after editing the icon design.

### Changed
- **NUKE META button rebuilt as a Canvas** — macOS Tk's native `Button` widget ignores `bg`/`disabledforeground` and renders the system cream/light appearance, which made the white label nearly invisible regardless of state. Replaced with a `tk.Canvas` that draws a DarkRed (`#8B0000`) button with a brighter-red (`#cc0000`) border, a thin inner top highlight for a raised feel, and a 16pt bold Menlo label. The disabled state shows a dark grey (`#3a3a3a`) button with a medium-grey (`#999999`) label — clearly readable, with the cursor switching to `arrow` instead of `hand2`. State changes go through a new `self._set_nuke_button_state('normal' | 'disabled')` helper.
- **App icon redesigned** — the old icon was a radiation symbol on a transparent square, which rendered as a blocky tile in Finder/Dock. Replaced with a proper macOS squircle: dark warm gradient (`#1a0c0c` → `#080202`) background, dark-red (`#8B0000`) edge ring, and the radiation trefoil centred on it in yellow/orange.
- **Drop zone polished** — replaced the flat red `Frame` with a `Canvas`-based targeting-reticle: dark red background (`#0d0303`), double border for depth, and bright-red corner brackets in each corner for a tactical/forensic feel. The gawdy fire-engine red is gone; the red now reads as an accent rather than a wall of colour.
- **State-aware reticle colours** — the corner brackets and double-border switch colour based on context: muted red (`#aa0000`) when idle, bright red (`#ff3300`) on drag-over, green (`#00cc66`) when targets are locked, orange (`#ffaa00`) while a nuke is in progress.

## [2026-06-01]

### Fixed
- **Drop zone invisible during drag-over** — on macOS the default tkinterdnd2 hover overlay washed out the gray drop-zone text (effectively white-on-white), so the user couldn't tell whether the drop target was active. Added `<<DropEnter>>` / `<<DropLeave>>` handlers that repaint the drop zone to dark red (`#cc0000`) with white text and a brighter red border while a file is being dragged over it, then restore the previous state (default or "✓ FILES LOADED" green) when the drag leaves.

## [2026-05-29]

### Fixed
- **Button text invisible in disabled state** — added `disabledforeground='#000000'` to the NUKE META button so text is black-on-grey and readable when no file is selected (previously white-on-grey, invisible).
- **Broken `/Applications` symlink** — the symlink in `/Applications` pointed to a stale path. Relinked to the current project directory and reset Launch Services cache so the app icon shows up correctly in Finder.
