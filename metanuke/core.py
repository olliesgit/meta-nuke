"""Core MetaNuke engine — pixel-reconstruction metadata stripper."""

import hashlib
import io
import os
import random
import re
import struct
import sys
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageCms

# HEIC/HEIF support via pillow-heif plugin
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False

# SVG namespace
SVG_NS = 'http://www.w3.org/2000/svg'

# PDF support via PyMuPDF
try:
    import fitz
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# Cache the sRGB ICC profile as a module singleton.
_SRGB_PROFILE = None
def _get_srgb_profile():
    global _SRGB_PROFILE
    if _SRGB_PROFILE is None:
        _SRGB_PROFILE = ImageCms.createProfile('sRGB')
    return _SRGB_PROFILE


class MetaNuke:
    """Nuclear-grade metadata stripper - strips EVERYTHING including color profiles."""

    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
                          '.webp', '.svg', '.avif'}
    if HEIF_AVAILABLE:
        SUPPORTED_FORMATS.update({'.heic', '.heif'})
    if PDF_AVAILABLE:
        SUPPORTED_FORMATS.add('.pdf')

    @staticmethod
    def scan_metadata(file_path: str) -> dict:
        """Scan a file and return a structured metadata report.

        Returns a dict with:
          name, path, size, format, dimensions, mode,
          info: dict of PIL image.info items,
          exif_keys: list of EXIF tag IDs,
          binary_markers: list of detected binary markers (EXIF, XMP, ICC, etc.),
          has_metadata: bool,
          icc_profile: bool,
          marker_details: human-readable list of what was found.
        """
        path = Path(file_path)
        result = {
            'name': path.name,
            'path': file_path,
            'size': path.stat().st_size if path.exists() else 0,
            'format': path.suffix.lower(),
            'dimensions': None,
            'mode': None,
            'info': {},
            'exif_keys': [],
            'binary_markers': [],
            'has_metadata': False,
            'icc_profile': False,
            'marker_details': [],
        }
        if not path.exists():
            return result

        try:
            with Image.open(file_path) as img:
                result['dimensions'] = (img.width, img.height)
                result['mode'] = img.mode
                info = dict(img.info)
                result['info'] = {}
                for k, v in info.items():
                    s = str(v)[:80]
                    result['info'][str(k)] = s

                # EXIF
                if hasattr(img, '_getexif'):
                    try:
                        exif = img._getexif()
                        if exif:
                            result['exif_keys'] = sorted(str(k) for k in exif.keys())
                    except Exception:
                        pass

                # ICC
                if 'icc_profile' in info:
                    result['icc_profile'] = True
                    result['binary_markers'].append('ICC_PROFILE')
                    result['marker_details'].append('ICC colour profile')

        except Exception as e:
            result['error'] = str(e)
            return result

        # Binary-level scan
        raw = path.read_bytes()
        markers = {
            b'Exif\x00\x00': ('EXIF', 'EXIF camera/GPS data'),
            b'<x:xmpmeta': ('XMP', 'XMP metadata packet'),
            b'ICC_PROFILE\x00': ('ICC_PROFILE', 'ICC colour profile'),
            b'Photoshop': ('Photoshop', 'Photoshop image data'),
            b'xmlns:dc=': ('DublinCore', 'Dublin Core metadata'),
            b'<rdf:RDF': ('RDF', 'RDF metadata'),
            b'<?xpacket': ('XMP', 'XMP metadata packet'),
        }
        for sig, (label, detail) in markers.items():
            if sig in raw:
                if label not in result['binary_markers']:
                    result['binary_markers'].append(label)
                    result['marker_details'].append(detail)

        # TIFF-specific
        if result['format'] in ('.tiff', '.tif'):
            if b'ImageDescription' in raw:
                result['binary_markers'].append('ImageDescription')
                result['marker_details'].append('TIFF image description')
            if b'Software' in raw:
                result['binary_markers'].append('Software')
                result['marker_details'].append('Software tag')

        result['has_metadata'] = bool(
            result['info'] or result['exif_keys'] or result['binary_markers']
        )
        return result

    @staticmethod
    def compare_metadata(before: dict, after_path: str) -> dict:
        """Compare metadata before and after nuking. Returns a diff dict."""
        after = MetaNuke.scan_metadata(after_path)
        removed_info = []
        for k in before.get('info', {}):
            if k not in after.get('info', {}):
                removed_info.append(k)
        removed_exif = []
        for k in before.get('exif_keys', []):
            if k not in after.get('exif_keys', []):
                removed_exif.append(k)
        removed_markers = []
        for m in before.get('binary_markers', []):
            if m not in after.get('binary_markers', []):
                removed_markers.append(m)
        return {
            'removed_info': removed_info,
            'removed_exif': removed_exif,
            'removed_markers': removed_markers,
            'was_clean': not before.get('has_metadata', False),
            'is_clean': not after.get('has_metadata', True),
        }

    @staticmethod
    def nuke_image(file_path: str, noise_level: int = 5,
                   output_path: str = None) -> tuple[bool, str]:
        """Completely strip ALL metadata from an image by reconstructing it
        from raw pixels.

        This is the nuclear option - we read only the pixel data and create a
        completely new image file. Nothing from the original file structure survives.

        STRIPS EVERYTHING:
        - EXIF data (camera, GPS, timestamps, etc.)
        - ICC color profiles (screen type, color calibration)
        - XMP/IPTC metadata
        - DPI/resolution info
        - Software fingerprints
        - Thumbnails and previews
        - Comments and descriptions
        - ALL other metadata

        Returns: (success: bool, message: str)
        """
        try:
            path = Path(file_path)

            # Validate file exists
            if not path.exists():
                return False, f"File not found: {file_path}"

            # Validate extension
            if path.suffix.lower() not in MetaNuke.SUPPORTED_FORMATS:
                return False, f"Unsupported format: {path.suffix}"

            # Animated GIFs need frame-by-frame handling to preserve animation.
            if path.suffix.lower() == '.gif':
                with Image.open(file_path) as probe:
                    if getattr(probe, 'n_frames', 1) > 1:
                        return MetaNuke._nuke_animated_gif(file_path)

            # SVG is XML-based, not pixel-based
            if path.suffix.lower() == '.svg':
                return MetaNuke._nuke_svg(file_path, output_path=output_path)

            # PDF via PyMuPDF
            if path.suffix.lower() == '.pdf':
                return MetaNuke._nuke_pdf(file_path, output_path=output_path)

            # Read the original image - ONLY extract pixel data
            with Image.open(file_path) as original:
                # Convert from any embedded color profile to sRGB first
                if 'icc_profile' in original.info:
                    try:
                        out_mode = 'RGBA' if original.mode == 'RGBA' else 'RGB'
                        original = ImageCms.profileToProfile(
                            original,
                            ImageCms.ImageCmsProfile(io.BytesIO(original.info['icc_profile'])),
                            _get_srgb_profile(),
                            outputMode=out_mode,
                        )
                    except Exception:
                        pass

                # Normalize to a safe mode
                if original.mode in ('RGB', 'RGBA', 'L', 'LA'):
                    src = original
                elif original.mode in ('P', 'PA') or 'A' in original.mode:
                    src = original.convert('RGBA')
                else:
                    src = original.convert('RGB')

                width, height = src.size
                original_mode = src.mode
                raw_bytes = src.tobytes()

            # Reconstruct from raw bytes
            clean_image = Image.frombytes(original_mode, (width, height), raw_bytes)
            clean_image.info = {}

            # Forensic noise (configurable)
            if noise_level > 0:
                clean_image = MetaNuke._add_forensic_noise(
                    clean_image, raw_bytes, original_mode, noise_level,
                )

            ext = path.suffix.lower()
            buffer = io.BytesIO()

            if ext in ('.jpg', '.jpeg'):
                if clean_image.mode == 'RGBA':
                    background = Image.new('RGB', clean_image.size, (255, 255, 255))
                    background.paste(clean_image, mask=clean_image.split()[3])
                    clean_image = background
                elif clean_image.mode == 'LA':
                    clean_image = clean_image.convert('L')
                elif clean_image.mode not in ('RGB', 'L'):
                    clean_image = clean_image.convert('RGB')
                clean_image.info = {}
                clean_image.save(
                    buffer, format='JPEG', quality=95, optimize=True,
                    exif=b'', icc_profile=None, subsampling='4:4:4',
                    qtables='web_high',
                )
                buffer.seek(0)
                buffer = MetaNuke._strip_jpeg_metadata(buffer)

            elif ext == '.png':
                if clean_image.mode == 'LA':
                    pass
                elif clean_image.mode not in ('RGB', 'RGBA', 'L'):
                    if 'A' in original_mode:
                        clean_image = clean_image.convert('RGBA')
                    else:
                        clean_image = clean_image.convert('RGB')
                clean_image.info = {}
                clean_image.save(buffer, format='PNG', optimize=True,
                                 icc_profile=None, pnginfo=None)
                buffer.seek(0)
                buffer = MetaNuke._strip_png_chunks(buffer)

            elif ext == '.gif':
                if clean_image.mode not in ('P', 'L', 'RGB', 'RGBA'):
                    clean_image = clean_image.convert('RGB')
                clean_image.info = {}
                clean_image.save(buffer, format='GIF')
                buffer.seek(0)
                buffer = MetaNuke._strip_gif_metadata(buffer)

            elif ext == '.bmp':
                clean_image.info = {}
                clean_image.save(buffer, format='BMP')

            elif ext in ('.tiff', '.tif'):
                clean_image.info = {}
                clean_image.save(buffer, format='TIFF', compression='none')
                buffer.seek(0)
                buffer = MetaNuke._strip_tiff_metadata(buffer)

            elif ext == '.webp':
                clean_image.info = {}
                clean_image.save(buffer, format='WEBP', quality=95,
                                 icc_profile=None, exif=b'')

            # Double-encode JPEGs to destroy compression fingerprints
            if ext in ('.jpg', '.jpeg'):
                buffer = MetaNuke._double_encode_jpeg(buffer)

            # Atomic write
            write_path = output_path if output_path else file_path
            buffer.seek(0)
            MetaNuke._atomic_write(write_path, buffer.read())

            if output_path:
                MetaNuke._strip_xattrs(write_path)
                MetaNuke._reset_file_timestamps(write_path)
            else:
                MetaNuke._strip_xattrs(file_path)
                MetaNuke._reset_file_timestamps(file_path)

            # Verify
            success, verify_msg = MetaNuke._verify_clean(write_path)
            if not success:
                return False, f"Verification failed: {verify_msg}"

            final_size = os.path.getsize(write_path)
            final_hash = MetaNuke._sha256(write_path)
            return True, f"NUKED: {path.name} ({final_size} bytes, sha256:{final_hash[:16]}...)"

        except Exception as e:
            return False, f"Error processing {file_path}: {str(e)}"

    @staticmethod
    def _sha256(file_path: str) -> str:
        """Get SHA256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, 'rb', 131072) as f:
            while True:
                chunk = f.read(131072)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _nuke_svg(file_path: str, output_path: str = None) -> tuple[bool, str]:
        """Strip metadata from an SVG by XML parsing and reconstruction."""
        try:
            import xml.etree.ElementTree as ET

            path = Path(file_path)
            raw = path.read_text(encoding='utf-8')
            root = ET.fromstring(raw)

            # Remove metadata-bearing elements
            for el in list(root.iter('{http://www.w3.org/2000/svg}metadata')):
                root.remove(el)
            for el in list(root.iter('{http://www.w3.org/2000/svg}desc')):
                root.remove(el)
            for el in list(root.iter('{http://www.w3.org/2000/svg}title')):
                root.remove(el)

            # Remove extra namespace declarations
            attribs_to_del = []
            for attr in root.attrib:
                if attr.startswith('xmlns:') and attr != 'xmlns':
                    attribs_to_del.append(attr)
                elif attr.startswith('{') and 'metadata' in attr.lower():
                    attribs_to_del.append(attr)
            for attr in attribs_to_del:
                del root.attrib[attr]

            ET.register_namespace('', SVG_NS)
            clean_xml = ET.tostring(root, encoding='unicode', xml_declaration=False)

            # Strip comments and PIs
            clean_xml = re.sub(r'<!--.*?-->', '', clean_xml, flags=re.DOTALL)
            clean_xml = re.sub(r'<\?[^>]+\?>', '', clean_xml)

            target = Path(output_path) if output_path else path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(clean_xml.strip() + '\n', encoding='utf-8')

            final_size = target.stat().st_size
            return True, f"NUKED: {path.name} ({final_size} bytes)"

        except ET.ParseError as e:
            return False, f"SVG parse error: {e}"
        except Exception as e:
            return False, f"Error processing SVG {file_path}: {str(e)}"

    @staticmethod
    def _nuke_pdf(file_path: str, output_path: str = None) -> tuple[bool, str]:
        """Strip metadata from a PDF using PyMuPDF."""
        try:
            import fitz
            path = Path(file_path)
            doc = fitz.open(file_path)

            doc.set_metadata({})
            try:
                doc.del_xml_metadata()
            except Exception:
                pass

            # Strip metadata from embedded images
            for page_num in range(len(doc)):
                page = doc[page_num]
                for img_ref in page.get_images():
                    xref = img_ref[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n < 5:
                            clean_pix = fitz.Pixmap(fitz.csRGB, pix)
                            doc.replace_image(xref, pixmap=clean_pix)
                            clean_pix = None
                        pix = None
                    except Exception:
                        pass

            target = Path(output_path) if output_path else path
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_pdf = target.with_suffix('.pdf.tmp')
            doc.save(str(tmp_pdf), garbage=4, deflate=True, clean=True)
            doc.close()
            os.replace(str(tmp_pdf), str(target))

            final_size = target.stat().st_size
            return True, f"NUKED: {path.name} ({final_size} bytes)"

        except Exception as e:
            return False, f"Error processing PDF {file_path}: {str(e)}"

    @staticmethod
    def _nuke_animated_gif(file_path: str) -> tuple[bool, str]:
        """Strip metadata from an animated GIF without touching animation."""
        try:
            path = Path(file_path)
            with open(file_path, 'rb') as f:
                raw = f.read()
            buffer = MetaNuke._strip_gif_metadata(io.BytesIO(raw))
            buffer.seek(0)
            MetaNuke._atomic_write(file_path, buffer.read())
            MetaNuke._strip_xattrs(file_path)
            MetaNuke._reset_file_timestamps(file_path)
            success, verify_msg = MetaNuke._verify_clean(file_path)
            if not success:
                return False, f"Verification failed: {verify_msg}"
            final_size = os.path.getsize(file_path)
            return True, f"NUKED (animated): {path.name} ({final_size} bytes)"
        except Exception as e:
            return False, f"Error processing {file_path}: {str(e)}"

    @staticmethod
    def _strip_png_chunks(png_buffer: io.BytesIO) -> io.BytesIO:
        """Remove ALL non-essential PNG chunks."""
        png_buffer.seek(0)
        data = png_buffer.read()
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            return png_buffer
        output = io.BytesIO()
        output.write(data[:8])
        essential = {b'IHDR', b'IDAT', b'IEND', b'PLTE', b'tRNS'}
        pos = 8
        while pos < len(data):
            if pos + 8 > len(data):
                break
            length = struct.unpack('>I', data[pos:pos+4])[0]
            chunk_type = data[pos+4:pos+8]
            if chunk_type in essential:
                output.write(data[pos:pos+12+length])
            pos += 12 + length
        output.seek(0)
        return output

    @staticmethod
    def _strip_jpeg_metadata(jpeg_buffer: io.BytesIO) -> io.BytesIO:
        """Strip ALL metadata segments from JPEG at binary level."""
        jpeg_buffer.seek(0)
        data = jpeg_buffer.read()
        if data[:2] != b'\xff\xd8':
            return jpeg_buffer
        output = io.BytesIO()
        output.write(b'\xff\xd8')
        pos = 2
        while pos < len(data) - 1:
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker == 0xD9:
                output.write(b'\xff\xd9')
                break
            if marker == 0xDA:
                output.write(data[pos:])
                break
            if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01):
                output.write(data[pos:pos+2])
                pos += 2
                continue
            if pos + 4 > len(data):
                break
            length = struct.unpack('>H', data[pos+2:pos+4])[0]
            if marker in (0xDB, 0xC4, 0xDD) or (0xC0 <= marker <= 0xCF and marker != 0xC4):
                output.write(data[pos:pos+2+length])
            pos += 2 + length
        output.seek(0)
        return output

    GIF_APP_KEEP = {b'NETSCAPE2.0', b'ANIMEXTS1.0'}

    @staticmethod
    def _strip_gif_metadata(gif_buffer: io.BytesIO) -> io.BytesIO:
        """Structural GIF parser that strips metadata-bearing extension blocks."""
        gif_buffer.seek(0)
        data = gif_buffer.read()
        n = len(data)
        if n < 13 or data[:3] not in (b'GIF', b'gif'):
            return gif_buffer

        def skip_sub_blocks(p):
            while p < n and data[p] != 0:
                p += 1 + data[p]
                if p > n:
                    return -1
            return p + 1 if p < n else -1

        try:
            out = bytearray()
            out += data[:13]
            pos = 13
            packed = data[10]
            if packed & 0x80:
                gct_size = 3 * (1 << ((packed & 0x07) + 1))
                if pos + gct_size > n:
                    return gif_buffer
                out += data[pos:pos + gct_size]
                pos += gct_size
            while pos < n:
                introducer = data[pos]
                if introducer == 0x3B:
                    out += b'\x3B'
                    break
                if introducer == 0x2C:
                    if pos + 10 > n:
                        return gif_buffer
                    img_packed = data[pos + 9]
                    block_end = pos + 10
                    if img_packed & 0x80:
                        lct_size = 3 * (1 << ((img_packed & 0x07) + 1))
                        block_end += lct_size
                    block_end += 1
                    sub_end = skip_sub_blocks(block_end)
                    if sub_end < 0:
                        return gif_buffer
                    out += data[pos:sub_end]
                    pos = sub_end
                    continue
                if introducer == 0x21:
                    if pos + 2 > n:
                        return gif_buffer
                    label = data[pos + 1]
                    ext_data_start = pos + 2
                    sub_end = skip_sub_blocks(ext_data_start)
                    if sub_end < 0:
                        return gif_buffer
                    keep = True
                    if label in (0xFE, 0x01):
                        keep = False
                    elif label == 0xFF:
                        keep = False
                        if (ext_data_start < n
                                and data[ext_data_start] == 11
                                and ext_data_start + 12 <= n):
                            app_id = bytes(data[ext_data_start + 1:ext_data_start + 12])
                            if app_id in MetaNuke.GIF_APP_KEEP:
                                keep = True
                    if keep:
                        out += data[pos:sub_end]
                    pos = sub_end
                    continue
                return gif_buffer
            return io.BytesIO(bytes(out))
        except Exception:
            return gif_buffer

    @staticmethod
    def _strip_tiff_metadata(tiff_buffer: io.BytesIO) -> io.BytesIO:
        """TIFF metadata - Pillow's re-save handles this."""
        return tiff_buffer

    @staticmethod
    def _add_forensic_noise(image: Image.Image, raw_bytes: bytes,
                            original_mode: str,
                            noise_level: int = 5) -> Image.Image:
        """Add imperceptible noise to defeat LSB steganography detection."""
        if original_mode not in ('RGB', 'RGBA', 'L', 'LA') or noise_level <= 0:
            return image
        bands = len(image.getbands())
        raw = bytearray(raw_bytes)
        num_pixels = image.size[0] * image.size[1]
        gate_threshold = min(255, max(10, noise_level * 25))
        max_delta = min(3, max(1, noise_level // 4))
        gate = random.randbytes(num_pixels)
        noise = random.randbytes(len(raw))
        for p in range(num_pixels):
            if gate[p] < gate_threshold:
                base = p * bands
                for c in range(bands):
                    direction = noise[base + c] % 3
                    if direction == 0:
                        v = raw[base + c] - max_delta
                        raw[base + c] = 0 if v < 0 else v
                    elif direction == 2:
                        v = raw[base + c] + max_delta
                        raw[base + c] = 255 if v > 255 else v
        noisy_image = Image.frombytes(original_mode, image.size, bytes(raw))
        noisy_image.info = {}
        return noisy_image

    @staticmethod
    def _double_encode_jpeg(jpeg_buffer: io.BytesIO) -> io.BytesIO:
        """Re-encode JPEG to destroy compression artifact fingerprints."""
        jpeg_buffer.seek(0)
        try:
            with Image.open(jpeg_buffer) as img:
                img.info = {}
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=94, optimize=True,
                         exif=b'', icc_profile=None, subsampling='4:4:4')
                output.seek(0)
                output = MetaNuke._strip_jpeg_metadata(output)
                return output
        except Exception:
            jpeg_buffer.seek(0)
            return jpeg_buffer

    @staticmethod
    def _atomic_write(file_path: str, data: bytes):
        """Atomic write via temp file + rename (drops SIP xattrs on macOS)."""
        target = Path(file_path)
        tmp = target.with_name(f'.{target.name}.metanuke.tmp')
        try:
            with open(tmp, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, file_path)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def _strip_xattrs(file_path: str):
        """Remove all extended file attributes (macOS quarantine, etc.)."""
        import subprocess
        if hasattr(os, 'listxattr') and hasattr(os, 'removexattr'):
            try:
                for attr in os.listxattr(file_path):
                    try:
                        os.removexattr(file_path, attr)
                    except OSError:
                        pass
            except OSError:
                pass
            return
        if sys.platform == 'darwin':
            try:
                subprocess.run(['/usr/bin/xattr', '-c', file_path],
                               check=False, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass

    @staticmethod
    def _reset_file_timestamps(file_path: str):
        """Reset file timestamps to current time."""
        try:
            current_time = time.time()
            os.utime(file_path, (current_time, current_time))
        except Exception:
            pass

    @staticmethod
    def _verify_clean(file_path: str) -> tuple[bool, str]:
        """Paranoid structural verification that image is truly clean."""
        try:
            with Image.open(file_path) as img:
                if hasattr(img, '_getexif'):
                    try:
                        exif = img._getexif()
                        if exif and len(exif) > 0:
                            return False, "EXIF data still present"
                    except Exception:
                        pass
                if hasattr(img, 'info') and img.info:
                    critical_keys = {
                        'exif', 'icc_profile', 'xmp', 'iptc', 'photoshop',
                        'adobe', 'adobe_transform', 'comment', 'comments',
                        'icc_profile_name', 'software', 'datetime',
                        'gps', 'make', 'model', 'artist', 'copyright',
                    }
                    for key in img.info:
                        key_lower = key.lower() if isinstance(key, str) else str(key).lower()
                        if key_lower in critical_keys:
                            return False, f"Critical metadata still present: {key}"
            with open(file_path, 'rb') as f:
                raw_data = f.read()
            ext = Path(file_path).suffix.lower()
            if ext in ('.jpg', '.jpeg'):
                result = MetaNuke._verify_jpeg_structure(raw_data)
                if result:
                    return False, result
            elif ext == '.png':
                result = MetaNuke._verify_png_structure(raw_data)
                if result:
                    return False, result
            if b'Exif\x00\x00' in raw_data:
                return False, "EXIF header found in file"
            if b'<x:xmpmeta' in raw_data or b'<?xpacket' in raw_data:
                return False, "XMP metadata packet found"
            if b'ICC_PROFILE\x00' in raw_data:
                return False, "ICC profile marker found"
            return True, "FORENSICALLY CLEAN - Verified"
        except Exception as e:
            return False, f"Verification error: {str(e)}"

    @staticmethod
    def _verify_jpeg_structure(data: bytes) -> Optional[str]:
        """Verify JPEG has no APP1-APP15 or COM segments."""
        if len(data) < 2 or data[0:2] != b'\xff\xd8':
            return None
        forbidden = {0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9,
                     0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xFE}
        names = {
            0xE1: "APP1 (EXIF/XMP)", 0xE2: "APP2 (ICC Profile)",
            0xEC: "APP12 (Ducky)", 0xED: "APP13 (IPTC/Photoshop)",
            0xEE: "APP14 (Adobe)", 0xEF: "APP15", 0xFE: "COM (Comment)",
        }
        pos = 2
        while pos < len(data) - 1:
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xD9, 0xDA):
                break
            if marker in forbidden:
                return f"JPEG metadata segment found: {names.get(marker, f'0x{marker:02X}')}"
            if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01, 0x00):
                pos += 2
            elif pos + 4 <= len(data):
                length = struct.unpack('>H', data[pos+2:pos+4])[0]
                pos += 2 + length
            else:
                break
        return None

    @staticmethod
    def _verify_png_structure(data: bytes) -> Optional[str]:
        """Verify PNG has no metadata chunks."""
        if len(data) < 8 or data[0:8] != b'\x89PNG\r\n\x1a\n':
            return None
        allowed = {b'IHDR', b'PLTE', b'tRNS', b'IDAT', b'IEND'}
        meta = {
            b'tEXt': "tEXt", b'iTXt': "iTXt", b'zTXt': "zTXt",
            b'tIME': "tIME", b'pHYs': "pHYs", b'gAMA': "gAMA",
            b'cHRM': "cHRM", b'sRGB': "sRGB", b'iCCP': "iCCP",
            b'bKGD': "bKGD", b'hIST': "hIST", b'sBIT': "sBIT",
            b'sPLT': "sPLT", b'eXIf': "eXIf",
        }
        pos = 8
        while pos < len(data) - 8:
            if pos + 8 > len(data):
                break
            length = struct.unpack('>I', data[pos:pos+4])[0]
            chunk_type = data[pos+4:pos+8]
            if chunk_type not in allowed:
                name = meta.get(chunk_type, chunk_type.decode('ascii', errors='replace'))
                return f"PNG metadata chunk found: {name}"
            pos += 12 + length
            if chunk_type == b'IEND':
                break
        return None
