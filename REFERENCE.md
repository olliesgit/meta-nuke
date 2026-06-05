# META NUKE Reference

Detailed architecture and verification docs. CLAUDE.md has the security invariants.

## Code Architecture

Single Python file (`meta_nuke.py`) with two classes.

### MetaNuke (Core Engine)

Entry point: `nuke_image(file_path)` — orchestrates the entire stripping process.

**Multi-layered stripping:**
1. **Pixel reconstruction**: Reads ONLY raw pixel data, creates new image from scratch
2. **Format-specific binary stripping**: Paranoid binary-level stripping per format
3. **Forensic countermeasures**:
   - `_add_forensic_noise()`: Imperceptible pixel noise defeats LSB steganography detection
   - `_double_encode_jpeg()`: Re-encodes JPEGs to destroy compression artifact fingerprints
   - `_reset_file_timestamps()`: Resets filesystem timestamps defeats timeline analysis
4. **Structural verification**: Parses file format structure to confirm no metadata segments exist

**Binary-level strippers:**
- `_strip_png_chunks()`: Removes all non-essential PNG chunks (keeps IHDR, IDAT, IEND, PLTE, tRNS)
- `_strip_jpeg_metadata()`: Strips all JPEG APP segments and comments
- `_strip_gif_metadata()`: Removes comment and application extension blocks
- `_strip_tiff_metadata()`: TIFF handling (relies on pixel reconstruction)

Why multi-layered: Camera manufacturers, Adobe, and forensic tools embed metadata in multiple locations. Single-pass PIL stripping is insufficient.

### MetaNukeGUI (User Interface)

Tkinter GUI with drag-and-drop (tkinterdnd2). Falls back to file dialog if drag-and-drop unavailable.

Key methods: `_on_drop()` / `_browse_files()` (file selection), `_set_file()` (validation), `_nuke()` (execution with confirmation).

## Verification System

`_verify_clean()` uses structural verification (not string pattern matching) for 100% reliability.

**Layer 1 — PIL-level:**
- Checks EXIF via `_getexif()` is empty
- Checks `img.info` dict for critical metadata keys

**Layer 2 — Binary structural:**
- `_verify_jpeg_structure()`: Parses JPEG segment markers, rejects APP1-APP15 or COM segments
- `_verify_png_structure()`: Parses PNG chunk structure, only allows IHDR/PLTE/tRNS/IDAT/IEND
- All formats: Checks for EXIF header (`Exif\x00\x00`), XMP packets (`<x:xmpmeta`), ICC markers

Why structural: String pattern matching (searching for "GPS" or "Canon") causes false positives when those bytes appear in compressed image data. Structural verification checks for actual metadata segments — 100% reliable.

## Testing

1. Test with images from multiple sources (cameras, phones, edited)
2. Verify with `exiftool image.jpg` — should show minimal/no metadata
3. Test all supported formats
4. Use hex editor to inspect for metadata signatures
5. Confirm forensic countermeasures work (noise, double-encoding, timestamp reset)
