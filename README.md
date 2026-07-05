# ☢️ META NUKE ☢️

**FORENSICALLY SAFE • NUCLEAR METADATA DESTRUCTION**

A bulletproof, 100% offline tool to completely strip ALL metadata from images, SVGs, and PDFs. Designed for life-or-death scenarios where forensic analysis must find nothing.

---

## 🚀 Quick Start

### Double-Click to Run
Simply double-click **`Meta Nuke.app`** in Finder to launch the GUI.

### Command Line
```bash
./run.sh
```

Or with a file:
```bash
./run.sh image.jpg
```

---

## 📋 Supported Formats

| Format | Notes |
|--------|-------|
| `.jpg` / `.jpeg` | EXIF, ICC, XMP, comments stripped |
| `.png` | tEXt, iTXt, zTXt, tIME, pHYs, all ancillary chunks |
| `.gif` | Comment blocks, app extensions |
| `.bmp` | Minimal metadata, full strip |
| `.tiff` / `.tif` | IFD metadata stripped |
| `.webp` | EXIF, ICC stripped |
| `.svg` | `<metadata>`, `<desc>`, `<title>`, XML comments, namespaces |
| `.avif` | Via Pillow 10+ |
| `.heic` / `.heif` | iPhone photos (needs `pillow-heif`) |
| `.pdf` | Document metadata, XMP, embedded image metadata (needs PyMuPDF) |

---

## 🛡️ What Gets NUKED

**ALL Metadata:**
- EXIF (camera make/model/serial, lens, firmware)
- GPS coordinates and location data
- Timestamps (creation, modification, digitization)
- ICC color profiles (screen type, calibration)
- IPTC/XMP (copyright, author, keywords)
- Software fingerprints (Photoshop, Lightroom, etc.)
- Camera brand signatures (Canon, Nikon, Sony, Apple, etc.)
- Thumbnails and previews
- PNG metadata chunks (tEXt, iTXt, pHYs, gAMA, etc.)
- JPEG APP segments and comments
- SVG `<metadata>`, `<desc>`, `<title>`, XML comments, processing instructions
- PDF document metadata (author, creator, producer) and XMP

|**Forensic Countermeasures:**
|- Per-pixel CSPRNG noise injection (±1–3, gated ~25% of pixels at default level 5)
|- JPEG double-encode with random quantization tables (quality 91–96) to mask tool fingerprint
|- Filesystem timestamp analysis defeated (zeroed to wall-clock time)
|- xattr stripping (macOS quarantine, Spotlight comments, Finder labels)
|- Configurable noise level 0–10 (0 = lossless, no perturbation)

---

## 🖥️ CLI Usage

```bash
python meta_nuke.py [options] [FILE ...]
```

### Options

| Flag | Description |
|------|-------------|
| `--dir DIR` / `-d` | Process all images in a directory |
| `--recursive` / `-r` | Recurse into subdirectories (with --dir) |
| `--output DIR` / `-o` | Save to output directory (default: overwrite) |
| `--backup` / `-b` | Keep a `.bak` copy of each original (in-place mode) |
| `--noise-level N` / `-n` | Forensic noise 0-10 (0=lossless, 5=default, 10=max) |
| `--strict` | Fail on silently-swallowed operations (ICC, PDF image) |
| `--jobs N` / `-j` | Parallel workers (default 1; single-threaded) |
| `--rename` | Write SHA256 content-hash filenames (requires --output) |
| `--preview` / `-p` | Show metadata without nuking |
| `--ask-noise` | Prompt before applying forensic noise to each file |
| `--log FILE` / `-l` | Append audit log to FILE |
| `--json` | Machine-readable JSON output |
| `--no-banner` | Suppress ASCII logo |
| `--gui` | Force GUI mode |
| `--version` | Show version |
| `--help` | Show help |

### Examples

```bash
# Single file
meta_nuke image.jpg

# Batch directory with separate output
meta_nuke --dir ./photos --recursive --output ./clean

# Lossless mode (no noise)
meta_nuke --noise-level 0 image.jpg

# Preview metadata only
meta_nuke --preview *.jpg

# JSON output for scripting
meta_nuke --json --no-banner *.jpg > results.json

# Audit trail
meta_nuke --log nuke.log --dir ./batch
```

---

## 🎨 GUI Features

- **Drag-and-drop** files or entire directories
- **Noise level slider** — 0 (lossless) to 10 (maximum)
- **Output directory picker** — save to separate folder
- **Preview button** — inspect metadata before nuking
- **Audit log toggle** — timestamped results file
- **Visual progress bar** — during bulk processing
- **SHA256 hashes** — shown in results dialog
- **Config persistence** — `~/.metanukerc` saves preferences between sessions

---

## ⚙️ Installation

```bash
./setup.sh
```

This creates a virtual environment and installs:
- Pillow (image processing)
- pillow-heif (HEIC/HEIF support)
- PyMuPDF (PDF support)
- tqdm (progress bars)
- tkinterdnd2 (drag-and-drop, optional)
- numpy (optional — ~50–100× faster forensic noise on large images)

### Build a standalone app

The bundled `Meta Nuke.app` is a lightweight launcher that runs from the project
venv. To build a **fully self-contained** app (no Python, pyenv, or venv required
on the target machine — copy it anywhere or hand it to anyone):

```bash
./build_app.sh
cp -R "dist/Meta Nuke.app" /Applications/
```

This uses PyInstaller and bundles a matching `tkdnd`, so drag-and-drop works
regardless of the host's Tcl/Tk.

---

## 🔒 Privacy & Security

- **100% OFFLINE** — Never touches the network, ever
- **100% LOCAL** — All processing happens on your machine
- **NO LOGGING** — Unless you enable audit log
- **NO CLOUD** — Nothing is uploaded anywhere

---

## 🧪 Verification

After nuking, verify with:

```bash
exiftool image.jpg       # Should show minimal/no metadata
python tests/test_smoke.py  # 98 smoke tests (no external deps)
```

---

## 📝 License

MIT — Use at your own risk. Designed for legitimate privacy protection.

---

**☢️ NUCLEAR METADATA DESTRUCTION - NO TRACES LEFT BEHIND ☢️**
