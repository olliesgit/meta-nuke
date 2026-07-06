# Changelog

## [2026-07-06] — v1.4.0

### Added
- **`--strict` flag** — ICC→sRGB conversion failures and other silently-swallowed operations are now reported as file failures (off by default; warnings are collected and logged)
- **`--jobs N` / `-j` flag** — multiprocessing batch processing via `multiprocessing.Pool`. Default 1 (single-threaded). Works without `tqdm`. Incompatible with `--ask-noise`.
- **`--rename` flag** — replaces output filename with the first 16 hex chars of the SHA256 hash, preventing filename-based information leakage. Requires `--output DIR`.
- **PDF comprehensive sanitisation** — now strips annotations (per-page), embedded file attachments, AcroForm form fields/widgets, catalog-level JavaScript/OpenAction, page-level /AA/JS, previous Names/Outlines/Dests catalog keys. RGBA pixmaps in embedded images are properly converted to RGB instead of silently dropping alpha.
- **GUI: Strict, Rename checkboxes** — new "Strict" and "Rename" checkbuttons in the options panel below "Keep backup". Config saved and restored on next launch.
- **TIFF binary-level metadata stripping** — `_strip_tiff_metadata` now walks the IFD chain and zeroes known metadata tag IDs (Make, Model, Software, Copyright, ImageDescription, EXIF/GPS IFD pointers, etc.)
- **TIFF structural verification** — `_verify_clean` now checks TIFF files for embedded metadata strings at binary level.
- **GIF structural verification** — `_verify_clean` now checks GIF files for surviving comment extension blocks.
- **SVG comprehensive sanitisation** — strips `<script>` elements, editor namespace elements/attributes (inkscape, sodipodi, etc.), xlink:href and external href values, and base64 data-URI `<image>` elements. Previously only stripped `<metadata>/<desc>/<title>`.
- **exiftool verification test** — `test_exiftool_verify` optionally shells out to exiftool (skips cleanly if absent) and asserts zero stored-image-metadata after nuking.
- **TIFF stripping regression test** — creates a TIFF with Make/Model/Software/Copyright tags, nukes, and verifies binary-level removal.
- **Comprehensive PDF regression test** — builds a PDF with annotations, embedded files, and AcroForm; verifies all three stripped after nuking.

### Changed
- **`_double_encode_jpeg` now randomized** — the second-encode quality varies per image (91–96 via `os.urandom`) instead of a fixed 94, so the tool does not imprint a single consistent quantization fingerprint.
- **`_double_encode_jpeg` skippable at lossless** — at `noise_level=0` the double-encode pass is skipped entirely, avoiding a second lossy JPEG pass in lossless mode.
- **README forensic claims corrected** — "LSB steganography detection defeated" → concrete per-pixel CSPRNG noise injection spec; "JPEG quantization fingerprinting eliminated" → random quantization tables documented; false precision removed.
- **SVG test made comprehensive** — now asserts editor namespaces stripped, `<script>` removed, external hrefs purged, and data-URI images sanitised.

### Fixed
- **ICC→sRGB conversion failures no longer silent** — the `except Exception: pass` now captures the error message and appends it to a warnings list (viewable with `--strict`).
- **PDF widget annotations not stripped** — `page.annots()` doesn't return widget/form-field annotations. Now nulls the page's `/Annots` array directly to catch them.
- **PDF RGBA pixmap alpha silently dropped** — embedded images with alpha channels were converted to RGB via `Pixmap(csRGB, pix)` which dropped the alpha channel; now pixels are blended onto white before conversion.
- **macOS Dock icon / foreground activation** — `_setup_macos_dock_icon()` failed silently because AppKit framework was never loaded (NSApp = None). Added `ctypes.cdll.LoadLibrary('AppKit')` before any objc calls; added `activateIgnoringOtherApps: True` so the window appears in the foreground.
- **Drag-and-drop broken on Apple Silicon** — `tkinterdnd2` 0.4.4+ ships an arm64 tkdnd binary compiled for Tcl 9 only, incompatible with CPython's Tcl/Tk 8.6. Pinned to `tkinterdnd2>=0.4.2,<0.4.4` which includes a native arm64 + Tcl 8.6 binary. Multi-file drop parsing also improved to handle macOS `file://` URL format and newline-separated paths.

## [2026-06-29] — v1.3.0

### Fixed
- **CRITICAL: HEIC/AVIF data loss** — `.heic`/`.heif`/`.avif` were listed as supported but had no save branch, so an in-place nuke overwrote the original with **zero bytes** (and reported failure). iPhone HEIC photos were the most common victim. Added proper re-encode branches plus an empty-buffer safety net that aborts *without writing* for any unhandled format.
- **EXIF orientation lost** — rotated photos (e.g. portrait iPhone shots) came out sideways because the pixel buffer was reconstructed without applying the EXIF Orientation tag. Now baked in via `ImageOps.exif_transpose` before metadata is discarded.
- **Verification gaps** — `_verify_clean` now structurally checks WebP (RIFF EXIF/XMP/ICCP chunks) in addition to JPEG/PNG, and only flags critical `info` keys that actually carry data (fixes false positives from plugins like pillow-heif that expose placeholder keys).

### Added
- **`--backup` / `-b` flag** (and GUI "Keep backup" checkbox) — preserves a `.bak` copy of each original before in-place overwrite.
- **numpy fast path for forensic noise** — optional `numpy` dependency (`pip install meta-nuke[fast]`) vectorizes the per-pixel noise loop (~50–100× faster on large photos). Pure-Python fallback retained when numpy is absent.
- **Standalone app build** — `build_app.sh` + `MetaNuke.spec` produce a fully self-contained `Meta Nuke.app` via PyInstaller, with no dependency on system Python / pyenv / the project venv. Bundles a matching `tkdnd`, so drag-and-drop works regardless of the host's Tcl/Tk.
- **Expanded regression tests** — orientation preservation, HEIC/AVIF not destroyed, WebP cleaning, lossless pixel preservation, noise bounds, and the backup flag (81 assertions, all passing).

### Changed
- **CSPRNG noise** — forensic noise now draws from `os.urandom` instead of the predictable Mersenne-Twister `random` module.
- **GUI drag-and-drop is now fault-tolerant** — if `tkinterdnd2`'s native library fails to load at runtime, the app falls back to a plain window (click-to-browse) instead of crashing on launch.

## [2026-06-21] — v1.2.0

### Added
- **Binary-level metadata diff** — new `MetaNuke.scan_metadata()` and `MetaNuke.compare_metadata()` methods produce structured metadata reports. Post-nuke dialog now shows exactly what was removed (info fields, EXIF tags, binary markers)
- **Drop onto NUKE button** — files can be dropped directly on the NUKE button to auto-start processing, skipping the extra click
- **macOS Quick Action** — `MetaNuke.workflow` bundle adds "Nuke with MetaNuke" to Finder right-click → Quick Actions. Install via `install-quick-action.sh`
- **Progress ETA** — batch processing now estimates and displays time remaining based on per-file speed
- **Lossless mode toggle** — one-click checkbox disables noise, sets slider to 0, uses max quality. Restores defaults when unchecked
- **Configurable output naming** — new "Name suffix" text field (e.g. `_nuked` turns `photo.jpg` → `photo_nuked.jpg`)
- **Keyboard shortcuts** — `⌘O` open files, `⌘N` nuke, `⌘P` preview, `⎋` clear selection
- **Tooltips on all controls** — hover delay of 400ms shows explanations on every interactive element (drop zone, noise, lossless, output, preview, audit log, NUKE button)
- **Enhanced metadata preview** — now shows PIL info fields, EXIF tag count, and detected binary markers (EXIF, XMP, ICC, Photoshop) in a structured view
- **`--ask-noise` CLI flag** — prompts before applying forensic noise to each file (y/N)

### Changed
- **Resizable window** — default 580×700, minimum 520×620. Expands to fit content
- **Button contrast** — bumped from `#4a4a4c` → `#6a6a6c` → `#9a9a9c` with black text after user feedback. Final ratio ~6:1 against card background
- **GUI refresh** — switched to Helvetica Neue, sentence case labels, card-based options panel, pill-shaped NUKE button concept (later simplified to rectangle)
- **Footer** — condensed to two lines, more subtle colour hierarchy
- **File info display** — single file now shows name, size, and dimensions (e.g. `photo.jpg · 2.4 MB · 1920 × 1080px`)

### Fixed
- **Invisible buttons in Save To section** — iterated from `#141414` card + `#3a3a3c` buttons through `#1c1c1e` + `#4a4a4c`, `#6a6a6c`, finally to `#9a9a9c` buttons which are clearly visible
- **Rounded rect rendering** — `create_polygon(smooth=True)` doesn't produce proper rounded corners in Tkinter. Replaced with simple `create_rectangle` for both drop zone border and NUKE button

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
