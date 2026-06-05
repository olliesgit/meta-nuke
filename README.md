# ☢️ META NUKE ☢️

**FORENSICALLY SAFE • NUCLEAR METADATA DESTRUCTION**

A bulletproof, 100% offline tool to completely strip ALL metadata from images. Designed for life-or-death scenarios where forensic analysis must find nothing.

---

## 🚀 Quick Start

### Double-Click to Run
Simply double-click **`Meta Nuke.app`** in Finder to launch the application.

### Command Line
```bash
./run.sh
```

Or with a file:
```bash
./run.sh /path/to/image.jpg
```

---

## ☢️ What Gets NUKED

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

**Forensic Countermeasures:**
- LSB steganography detection defeated
- JPEG quantization fingerprinting eliminated
- Filesystem timestamp analysis defeated
- Compression artifact patterns destroyed
- Statistical analysis patterns removed

---

## 🛡️ Forensic Safety Features

1. **Complete Reconstruction** - Reads ONLY raw pixels, creates brand new file
2. **Binary-Level Stripping** - Parses file format and removes ALL non-essential chunks
3. **Noise Injection** - Adds imperceptible pixel noise to destroy statistical patterns
4. **Double Encoding** - Re-encodes JPEGs to eliminate compression fingerprints
5. **Timestamp Reset** - Resets file system timestamps
6. **Verification** - Scans output for 50+ danger signatures before reporting success

---

## 📋 Supported Formats

- `.jpg` / `.jpeg`
- `.png`
- `.gif`
- `.bmp`
- `.tiff` / `.tif`
- `.webp`

---

## ⚙️ Installation

If you need to set up from scratch:

```bash
./setup.sh
```

This will:
- Create a Python virtual environment
- Install required dependencies (Pillow, tkinterdnd2)

---

## 🔒 Privacy & Security

- **100% OFFLINE** - Never touches the network, ever
- **100% LOCAL** - All processing happens on your machine
- **NO LOGGING** - No files are logged or tracked
- **NO CLOUD** - Nothing is uploaded anywhere

---

## ⚠️ Important Notes

- The tool **overwrites the original file** - make a backup if needed
- The image will look **identical** but forensic tools will find **nothing**
- Designed for scenarios where metadata leakage could be life-threatening
- Use responsibly and legally

---

## 🧪 Verification

After nuking, you can verify with:
```bash
exiftool image.jpg  # Should show minimal/no metadata
```

---

## 📝 License

Use at your own risk. Designed for legitimate privacy protection.

---

**☢️ NUCLEAR METADATA DESTRUCTION - NO TRACES LEFT BEHIND ☢️**


