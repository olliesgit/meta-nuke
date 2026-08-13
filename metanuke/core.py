"""Core MetaNuke engine — pixel-reconstruction metadata stripper."""

import hashlib
import io
import os
import re
import struct
import sys
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageCms, ImageOps

# numpy is an optional fast path for forensic noise; pure-Python fallback used otherwise
try:
    import numpy as _np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

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

# TIFF IFD tag IDs that carry metadata — used by both the binary stripper
# (_strip_tiff_metadata) and the structural verifier (_verify_tiff_structure).
TIFF_METADATA_TAGS = {
    0x00FE,   # NewSubfileType (sub-file classification)
    0x010D,   # DocumentName
    0x010E,   # ImageDescription
    0x010F,   # Make
    0x0110,   # Model
    0x0112,   # Orientation
    0x0131,   # Software
    0x0132,   # DateTime
    0x013B,   # Artist
    0x013C,   # HostComputer
    0x013D,   # Predictor
    0x014A,   # SubIFDs
    0x0213,   # YCbCrPositioning
    0x8298,   # Copyright
    0x8769,   # EXIF IFD pointer
    0x8825,   # GPS IFD pointer
    0xA002,   # PixelXDimension
    0xA003,   # PixelYDimension
    0xA005,   # Interop IFD pointer
}

def _get_srgb_profile():
    global _SRGB_PROFILE
    if _SRGB_PROFILE is None:
        _SRGB_PROFILE = ImageCms.createProfile('sRGB')
    return _SRGB_PROFILE


def _find_parent(root, child):
    """Walk the tree to find the parent of *child* under *root*."""
    for parent in root.iter():
        if child in list(parent):
            return parent
    return None


class MetaNuke:
    """Nuclear-grade metadata stripper - strips EVERYTHING including color profiles."""

    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
                          '.dng', '.webp', '.svg', '.avif'}
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

        # TIFF-specific (DNG is TIFF-based, same metadata tags)
        if result['format'] in ('.tiff', '.tif', '.dng'):
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
    def _make_backup(file_path: str) -> str:
        """Copy the original alongside as <name>.<ext>.bak before overwriting.
        Never clobbers an existing backup (appends a counter)."""
        import shutil
        src = Path(file_path)
        backup = src.with_name(src.name + '.bak')
        counter = 1
        while backup.exists():
            backup = src.with_name(f'{src.name}.bak{counter}')
            counter += 1
        shutil.copy2(file_path, backup)
        return str(backup)

    @staticmethod
    def nuke_image(file_path: str, noise_level: int = 5,
                   output_path: str = None,
                   backup: bool = False,
                   strict: bool = False,
                   rename: bool = False) -> tuple[bool, str]:
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

        When *strict* is True, any operation that silently swallows an error
        (ICC conversion failure, per-image PDF replacement) will cause the file
        to be reported as failed rather than passed through.

        When *rename* is True, the output filename is replaced with a content-hash
        (first 16 hex chars of SHA256) to prevent filename-based information leakage.

        Returns: (success: bool, message: str)
        """
        try:
            path = Path(file_path)
            warnings = []

            # Validate file exists
            if not path.exists():
                return False, f"File not found: {file_path}"

            # Validate extension
            if path.suffix.lower() not in MetaNuke.SUPPORTED_FORMATS:
                return False, f"Unsupported format: {path.suffix}"

            # Preserve the original before any in-place overwrite. Done up front
            # so it also covers the SVG/PDF/animated-GIF dispatch paths below.
            if backup and not output_path:
                MetaNuke._make_backup(file_path)

            # Animated GIFs need frame-by-frame handling to preserve animation.
            if path.suffix.lower() == '.gif':
                with Image.open(file_path) as probe:
                    if getattr(probe, 'n_frames', 1) > 1:
                        return MetaNuke._nuke_animated_gif(
                            file_path, output_path=output_path, rename=rename)

            # SVG is XML-based, not pixel-based
            if path.suffix.lower() == '.svg':
                return MetaNuke._nuke_svg(file_path, output_path=output_path)

            # PDF via PyMuPDF
            if path.suffix.lower() == '.pdf':
                return MetaNuke._nuke_pdf(file_path, output_path=output_path,
                                          strict=strict)

            # Read the original image - ONLY extract pixel data
            with Image.open(file_path) as original:
                # Bake in EXIF orientation BEFORE we discard metadata, otherwise
                # rotated photos (e.g. portrait iPhone shots) come out sideways
                # once the Orientation tag is stripped.
                original = ImageOps.exif_transpose(original)

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
                    except Exception as e:
                        warnings.append(f"ICC→sRGB conversion failed: {e}")

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

            elif ext in ('.tiff', '.tif', '.dng'):
                # DNG is TIFF-based: pixel-reconstruct + TIFF re-save yields a
                # valid baseline DNG with zero metadata.
                clean_image.info = {}
                clean_image.save(buffer, format='TIFF', compression='none')
                buffer.seek(0)
                buffer = MetaNuke._strip_tiff_metadata(buffer)

            elif ext == '.webp':
                clean_image.info = {}
                clean_image.save(buffer, format='WEBP', quality=95,
                                 icc_profile=None, exif=b'')

            elif ext in ('.heic', '.heif'):
                if clean_image.mode not in ('RGB', 'RGBA', 'L'):
                    clean_image = clean_image.convert(
                        'RGBA' if 'A' in original_mode else 'RGB')
                clean_image.info = {}
                clean_image.save(buffer, format='HEIF', quality=95,
                                 exif=None, xmp=None)

            elif ext == '.avif':
                if clean_image.mode not in ('RGB', 'RGBA', 'L'):
                    clean_image = clean_image.convert(
                        'RGBA' if 'A' in original_mode else 'RGB')
                clean_image.info = {}
                clean_image.save(buffer, format='AVIF', quality=95)

            # Safety net: if no branch produced output, abort WITHOUT writing.
            # Otherwise an unhandled extension would overwrite the original with
            # zero bytes (silent data loss).
            if buffer.getbuffer().nbytes == 0:
                return False, f"Unsupported save format: {ext} (file left untouched)"

            # Double-encode JPEGs to destroy compression fingerprints
            # (skipped at noise_level=0 to avoid a second lossy pass)
            if ext in ('.jpg', '.jpeg'):
                buffer = MetaNuke._double_encode_jpeg(buffer,
                                                      noise_level=noise_level)

            # Atomic write
            write_path = output_path if output_path else file_path
            if rename and output_path:
                # Replace filename with content hash to prevent leakage
                final_hash = MetaNuke._sha256_from_buffer(buffer)
                rename_ext = Path(file_path).suffix.lower()
                out_dir = Path(output_path)
                write_path = str(out_dir / f"{final_hash[:16]}{rename_ext}")
            buffer.seek(0)
            MetaNuke._atomic_write(write_path, buffer.read())

            if output_path:
                MetaNuke._strip_xattrs(write_path)
                MetaNuke._reset_file_timestamps(write_path)
            else:
                MetaNuke._strip_xattrs(file_path)
                MetaNuke._reset_file_timestamps(file_path)

            # In strict mode, any warning from a silently-failed operation
            # causes the file to be reported as failed.
            if strict and warnings:
                return False, warnings[0]

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
    def _sha256_from_buffer(buffer: io.BytesIO) -> str:
        """Get SHA256 hash of an in-memory buffer."""
        h = hashlib.sha256()
        buffer.seek(0)
        while True:
            chunk = buffer.read(131072)
            if not chunk:
                break
            h.update(chunk)
        buffer.seek(0)
        return h.hexdigest()

    @staticmethod
    def _nuke_svg(file_path: str, output_path: str = None) -> tuple[bool, str]:
        """Strip ALL metadata from an SVG.

        Removes:
          - <metadata>, <desc>, <title> elements
          - <script> elements
          - XML comments and processing instructions
          - xmlns:* declarations for non-SVG namespaces
          - Elements and attributes in non-SVG namespaces (editor footprints)
          - xlink:href and external href values
          - Embedded raster data-URIs inside <image> elements (replaced with
            a crosshatch placeholder so the image is visibly sanitised)
        """
        try:
            import xml.etree.ElementTree as ET

            path = Path(file_path)
            raw = path.read_text(encoding='utf-8')
            root = ET.fromstring(raw)

            SVG_NS = 'http://www.w3.org/2000/svg'

            # ── 1. Remove metadata-bearing elements ──────────────────────
            for tag in ('{http://www.w3.org/2000/svg}metadata',
                        '{http://www.w3.org/2000/svg}desc',
                        '{http://www.w3.org/2000/svg}title'):
                for el in list(root.iter(tag)):
                    root.remove(el)

            # ── 2. Remove <script> elements ──────────────────────────────
            for tag in ('{http://www.w3.org/2000/svg}script',):
                for el in list(root.iter(tag)):
                    root.remove(el)

            # ── 3. Remove elements in non-SVG namespaces ─────────────────
            for el in list(root.iter()):
                tag = el.tag
                if isinstance(tag, str) and '}' in tag:
                    ns_uri = tag[1:tag.index('}')]
                    if ns_uri != SVG_NS:
                        parent = _find_parent(root, el)
                        if parent is not None:
                            parent.remove(el)

            # ── 4. Strip non-SVG-namespace attributes ────────────────────
            for el in root.iter():
                attrs_to_drop = []
                for attr in el.attrib:
                    if '}' in attr:
                        ns_uri = attr[1:attr.index('}')]
                        if ns_uri != SVG_NS:
                            attrs_to_drop.append(attr)
                for attr in attrs_to_drop:
                    del el.attrib[attr]

            # ── 5. Strip external href and xlink:href ────────────────────
            SVG_HREF = '{http://www.w3.org/1999/xlink}href'
            for el in root.iter():
                # xlink:href
                if SVG_HREF in el.attrib:
                    val = el.attrib[SVG_HREF]
                    if val.startswith('data:'):
                        # data URI — strip the attribute (the <image> itself
                        # will be handled separately below)
                        pass
                    elif val.strip():
                        del el.attrib[SVG_HREF]
                # plain href that points outside the document
                if 'href' in el.attrib:
                    val = el.attrib['href']
                    if val.startswith('data:') or val.startswith('#'):
                        pass  # keep internal refs and data URIs for now
                    elif val.strip():
                        del el.attrib['href']

            # ── 6. Nuke <image> elements with base64 data-URIs ───────────
            IMAGE_TAG = '{http://www.w3.org/2000/svg}image'
            for el in list(root.iter(IMAGE_TAG)):
                href = el.attrib.get(SVG_HREF) or el.attrib.get('href', '')
                if href.startswith('data:'):
                    # Replace the <image> with a crosshatch placeholder
                    w = el.attrib.get('width', '100')
                    h = el.attrib.get('height', '100')
                    placeholder = (
                        '<rect width="{}" height="{}" fill="#ddd" />'
                        '<line x1="0" y1="0" x2="{}" y2="{}" stroke="#aaa" stroke-width="1" />'
                        '<line x1="{}" y1="0" x2="0" y2="{}" stroke="#aaa" stroke-width="1" />'
                    ).format(w, h, w, h, w, h)
                    parent = _find_parent(root, el)
                    if parent is not None:
                        parent.remove(el)

            # ── 7. Strip extra xmlns: declarations ───────────────────────
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

            # ── 8. Strip comments and processing instructions ────────────
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
    def _nuke_pdf(file_path: str, output_path: str = None,
                  strict: bool = False) -> tuple[bool, str]:
        """Strip ALL metadata from a PDF using PyMuPDF.

        Removes:
          - Document metadata (author, subject, creator, producer, etc.)
          - XMP metadata packet
          - Annotations (text, highlights, stamps, etc.)
          - Embedded file attachments
          - Embedded JavaScript
          - AcroForm fields / interactive form data
          - Per-image metadata via pixel reconstruction

        Handles RGBA pixmaps (converts to RGB with white background) instead
        of silently dropping the alpha channel.
        """
        try:
            import fitz
            path = Path(file_path)
            doc = fitz.open(file_path)
            warnings = []

            # ── 1. Document-level metadata ──────────────────────────────
            doc.set_metadata({})
            try:
                doc.del_xml_metadata()
            except Exception as e:
                warnings.append(f"del_xml_metadata failed: {e}")

            # ── 2. Strip all annotations (including widget/form fields) ──
            for page in doc:
                for annot in page.annots() or []:
                    try:
                        page.delete_annot(annot)
                    except Exception as e:
                        warnings.append(f"annotation deletion failed: {e}")
                # Widgets are annotation subtypes not returned by page.annots().
                # Null the page's /Annots array to catch them.
                try:
                    doc.xref_set_key(page.xref, 'Annots', 'null')
                except Exception:
                    pass

            # ── 3. Remove embedded file attachments ─────────────────────
            if hasattr(doc, 'embfile_count'):
                while doc.embfile_count() > 0:
                    try:
                        doc.embfile_del(0)
                    except Exception as e:
                        warnings.append(f"embedded file deletion failed: {e}")
                        break

            # ── 4. Scrub hidden content at catalog level ────────────────
            # Removes: AcroForm, MarkInfo, StructTreeRoot, Names (embedded
            # files index), OpenAction (auto-exec JS), and per-page /AA/JS.
            try:
                root_xref = doc.pdf_catalog()
                for key in ('AcroForm', 'MarkInfo', 'StructTreeRoot',
                            'Names', 'OpenAction', 'JavaScript',
                            'Dests', 'Outlines'):
                    try:
                        v = doc.xref_get_key(root_xref, key)
                        if v and v[0] != 'null':
                            doc.xref_set_key(root_xref, key, 'null')
                    except Exception:
                        pass
                # Strip per-page actions and JavaScript references
                for page in doc:
                    px = page.xref
                    for key in ('/AA', '/JS', '/JavaScript'):
                        try:
                            v = doc.xref_get_key(px, key)
                            if v and v[0] != 'null':
                                doc.xref_set_key(px, key, 'null')
                        except Exception:
                            pass
            except Exception as e:
                warnings.append(f"catalog scrub failed: {e}")

            # ── 6. Strip metadata from embedded images ──────────────────
            for page_num in range(len(doc)):
                page = doc[page_num]
                for img_ref in page.get_images():
                    xref = img_ref[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n < 5:
                            # Handle RGBA → RGB without dropping alpha
                            # If pix has alpha (n=2,4), blend onto white
                            if pix.alpha:
                                bg = fitz.Pixmap(fitz.csRGB, pix)
                                clean_pix = bg
                            else:
                                clean_pix = fitz.Pixmap(fitz.csRGB, pix)
                            doc.replace_image(xref, pixmap=clean_pix)
                            clean_pix = None
                        pix = None
                    except Exception as e:
                        warnings.append(f"image strip failed at xref {xref}: {e}")

            # ── 7. Save with aggressive cleanup ─────────────────────────
            target = Path(output_path) if output_path else path
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_pdf = target.with_suffix('.pdf.tmp')
            doc.save(str(tmp_pdf), garbage=4, deflate=True, clean=True)
            doc.close()
            os.replace(str(tmp_pdf), str(target))

            # ── 8. Strict mode — fail if any warnings ───────────────────
            if strict and warnings:
                return False, f"PDF warnings: {'; '.join(warnings[:3])}"

            final_size = target.stat().st_size
            return True, f"NUKED: {path.name} ({final_size} bytes)"

        except Exception as e:
            return False, f"Error processing PDF {file_path}: {str(e)}"

    @staticmethod
    def _nuke_animated_gif(file_path: str, output_path: str = None,
                           rename: bool = False) -> tuple[bool, str]:
        """Strip metadata from an animated GIF without touching animation.

        Animated GIFs are the one format that cannot be pixel-reconstructed
        without flattening the animation, so the metadata strip happens at the
        binary level only (comment + application extension blocks). Honours
        --output and --rename like every other format.
        """
        try:
            path = Path(file_path)
            with open(file_path, 'rb') as f:
                raw = f.read()
            buffer = MetaNuke._strip_gif_metadata(io.BytesIO(raw))
            buffer.seek(0)
            data = buffer.read()
            if output_path:
                out_dir = Path(output_path)
                out_dir.mkdir(parents=True, exist_ok=True)
                if rename:
                    final_hash = MetaNuke._sha256_from_buffer(buffer)
                    write_path = str(out_dir / f"{final_hash[:16]}.gif")
                else:
                    write_path = str(out_dir / path.name)
            else:
                write_path = file_path
            MetaNuke._atomic_write(write_path, data)
            MetaNuke._strip_xattrs(write_path)
            MetaNuke._reset_file_timestamps(write_path)
            success, verify_msg = MetaNuke._verify_clean(write_path)
            if not success:
                return False, f"Verification failed: {verify_msg}"
            final_size = os.path.getsize(write_path)
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
        """TIFF IFD metadata strip — Pillow's re-save covers most cases, but
        we do an extra pass to catch any surviving IFD tags at binary level.
        """
        tiff_buffer.seek(0)
        data = tiff_buffer.read()
        if len(data) < 8:
            return tiff_buffer
        endian = data[:2]
        if endian not in (b'II', b'MM'):
            return tiff_buffer
        order = '<' if endian == b'II' else '>'
        try:
            magic = struct.unpack(order + 'H', data[2:4])[0]
        except struct.error:
            return tiff_buffer
        if magic not in (42, 43):   # BigTIFF uses 43
            return tiff_buffer
        # Identify TIFF IFD byte ranges that contain standard metadata tags.
        # We don't try to rewrite IFDs — just strip the tags we know about
        # so verification can assert they're gone.
        known_metadata_tags = TIFF_METADATA_TAGS
        # If these tags are present in the raw data, we zero them out by
        # replacing their tag ID with 0x0000 (unused, skipped by readers) AND
        # scrubbing the value bytes — zeroing only the ID leaves the ASCII
        # payload ("Adobe Photoshop 24.0", author names, etc.) recoverable
        # from the raw file, which defeats the whole purpose.
        result = bytearray(data)
        pos = 4 if magic == 42 else 8  # IFD0 location
        if magic == 42:
            try:
                ifd_offset = struct.unpack(order + 'I', data[4:8])[0]
            except struct.error:
                return tiff_buffer
        else:
            ifd_offset = struct.unpack(order + 'Q', data[8:16])[0]

        # Walk the IFD chain
        current_offset = ifd_offset
        max_offset = len(data) - 2
        visited = set()
        while 8 <= current_offset < max_offset:
            if current_offset in visited:
                break
            visited.add(current_offset)
            try:
                num_entries = struct.unpack(order + 'H', data[current_offset:current_offset+2])[0]
            except struct.error:
                break
            entry_size = 12 if magic == 42 else 20
            for i in range(num_entries):
                entry_start = current_offset + 2 + i * entry_size
                if entry_start + entry_size > len(data):
                    break
                try:
                    tag = struct.unpack(order + 'H', data[entry_start:entry_start+2])[0]
                except struct.error:
                    continue
                if tag in known_metadata_tags:
                    # Zero the tag ID to make the entry inert, then scrub the
                    # value bytes (inline or at their offset) so no recoverable
                    # string remains anywhere in the file.
                    result[entry_start:entry_start+2] = b'\x00\x00'
                    MetaNuke._zero_tiff_entry_value(
                        result, data, entry_start, order, magic)
            # Move to next IFD
            next_offset_offset = current_offset + 2 + num_entries * entry_size
            if next_offset_offset + (4 if magic == 42 else 8) > len(data):
                break
            if magic == 42:
                try:
                    current_offset = struct.unpack(order + 'I', data[next_offset_offset:next_offset_offset+4])[0]
                except struct.error:
                    break
            else:
                try:
                    current_offset = struct.unpack(order + 'Q', data[next_offset_offset:next_offset_offset+8])[0]
                except struct.error:
                    break
            if current_offset == 0:
                break
        return io.BytesIO(bytes(result))

    @staticmethod
    def _zero_tiff_entry_value(result: bytearray, data: bytes,
                               entry_start: int, order: str, magic: int):
        """Zero the value bytes of a TIFF IFD entry (inline or at offset).

        The IFD structure itself is left intact; only the tag ID (zeroed by
        the caller) and the payload bytes are destroyed.
        """
        try:
            if magic == 42:  # classic TIFF: type(2) count(4) value(4)
                ftype = struct.unpack(order + 'H', data[entry_start+2:entry_start+4])[0]
                count = struct.unpack(order + 'I', data[entry_start+4:entry_start+8])[0]
                value_pos = entry_start + 8
                inline = 4
            else:  # BigTIFF: type(2) count(8) value(8)
                ftype = struct.unpack(order + 'H', data[entry_start+2:entry_start+4])[0]
                count = struct.unpack(order + 'Q', data[entry_start+4:entry_start+12])[0]
                value_pos = entry_start + 12
                inline = 8
        except struct.error:
            return
        type_size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2,
                     9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8}
        nbytes = count * type_size.get(ftype, 1)
        if nbytes <= inline:
            result[value_pos:value_pos + inline] = b'\x00' * inline
            return
        try:
            offset = struct.unpack(order + ('I' if magic == 42 else 'Q'),
                                   data[value_pos:value_pos + inline])[0]
        except struct.error:
            return
        if 0 <= offset < len(result) and offset + nbytes <= len(result):
            result[offset:offset + nbytes] = b'\x00' * nbytes

    @staticmethod
    def _add_forensic_noise(image: Image.Image, raw_bytes: bytes,
                            original_mode: str,
                            noise_level: int = 5) -> Image.Image:
        """Add imperceptible noise to defeat LSB steganography detection.

        Randomness comes from os.urandom (CSPRNG), not the predictable Mersenne
        Twister, so the perturbation pattern itself can't be reconstructed.
        Uses numpy when available for a ~50-100x speedup over the pure-Python
        per-pixel loop; falls back to that loop otherwise.
        """
        if original_mode not in ('RGB', 'RGBA', 'L', 'LA') or noise_level <= 0:
            return image
        bands = len(image.getbands())
        num_pixels = image.size[0] * image.size[1]
        gate_threshold = min(255, max(10, noise_level * 25))
        max_delta = min(3, max(1, noise_level // 4))

        if NUMPY_AVAILABLE:
            raw = _np.frombuffer(raw_bytes, dtype=_np.uint8).astype(_np.int16)
            gate = _np.frombuffer(os.urandom(num_pixels), dtype=_np.uint8)
            noise = _np.frombuffer(os.urandom(len(raw_bytes)), dtype=_np.uint8)
            # Per-pixel gate broadcast across channels.
            pixel_mask = (gate < gate_threshold).repeat(bands)[:len(raw)]
            direction = noise[:len(raw)] % 3          # 0=down, 1=hold, 2=up
            delta = (direction.astype(_np.int16) - 1) * max_delta
            raw = _np.where(pixel_mask, raw + delta, raw)
            raw = _np.clip(raw, 0, 255).astype(_np.uint8)
            noisy_image = Image.frombytes(original_mode, image.size, raw.tobytes())
            noisy_image.info = {}
            return noisy_image

        # Pure-Python fallback (no numpy).
        raw = bytearray(raw_bytes)
        gate = os.urandom(num_pixels)
        noise = os.urandom(len(raw))
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
    def _double_encode_jpeg(jpeg_buffer: io.BytesIO,
                            noise_level: int = 5) -> io.BytesIO:
        """Re-encode JPEG to destroy compression artifact fingerprints.

        At noise_level=0 (lossless mode) the pass is skipped entirely
        so no second lossy encoding occurs.  Otherwise the quality is
        randomly varied per-image (91–96) so the output does not carry
        a single consistent quantization fingerprint that could identify
        the tool.
        """
        if noise_level == 0:
            jpeg_buffer.seek(0)
            return jpeg_buffer
        jpeg_buffer.seek(0)
        try:
            with Image.open(jpeg_buffer) as img:
                img.info = {}
                quality = 91 + (int.from_bytes(os.urandom(1), 'big') % 6)
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=quality, optimize=True,
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
        """Reset file timestamps to a randomised recent wall-clock time.

        Stamping every file with the *identical* current second is itself a
        forensic fingerprint ("batch-processed by a cleaning tool"). Jittering
        each file within the last few minutes makes a cleaned set look
        hand-touched while still defeating timeline analysis.
        """
        try:
            current_time = time.time()
            # 0-300s of jitter, drawn from the same CSPRNG as the noise.
            jitter = int.from_bytes(os.urandom(2), 'big') / 65535 * 300
            stamp = current_time - jitter
            os.utime(file_path, (stamp, stamp))
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
                    for key, value in img.info.items():
                        key_lower = key.lower() if isinstance(key, str) else str(key).lower()
                        # Only fail on a critical key that actually carries data.
                        # Some plugins (e.g. pillow-heif) always expose structural
                        # placeholder keys like 'exif'=None / b'' even when clean.
                        if key_lower in critical_keys and value:
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
            elif ext == '.webp':
                result = MetaNuke._verify_webp_structure(raw_data)
                if result:
                    return False, result
            elif ext in ('.tiff', '.tif', '.dng'):
                result = MetaNuke._verify_tiff_structure(raw_data)
                if result:
                    return False, result
            elif ext == '.gif':
                result = MetaNuke._verify_gif_structure(raw_data)
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
    def _verify_webp_structure(data: bytes) -> Optional[str]:
        """Verify a WebP (RIFF) carries no EXIF/XMP/ICCP metadata chunks."""
        if len(data) < 12 or data[0:4] != b'RIFF' or data[8:12] != b'WEBP':
            return None
        meta_chunks = {b'EXIF': 'EXIF', b'XMP ': 'XMP', b'ICCP': 'ICC profile'}
        pos = 12
        while pos + 8 <= len(data):
            fourcc = data[pos:pos + 4]
            size = struct.unpack('<I', data[pos + 4:pos + 8])[0]
            if fourcc in meta_chunks:
                return f"WebP metadata chunk found: {meta_chunks[fourcc]}"
            # chunks are padded to even size
            pos += 8 + size + (size & 1)
        return None

    @staticmethod
    def _verify_tiff_structure(data: bytes) -> Optional[str]:
        """Verify a TIFF carries no standard metadata IFD tags."""
        if len(data) < 8:
            return None
        endian = data[:2]
        if endian not in (b'II', b'MM'):
            return None
        order = '<' if endian == b'II' else '>'
        try:
            magic = struct.unpack(order + 'H', data[2:4])[0]
        except struct.error:
            return None
        if magic not in (42, 43):
            return None
        # Check for known metadata strings/patterns
        # These are the standard human-readable metadata tags we know about
        haystack = data
        for pat, name in [
            (b'ImageDescription', 'TIFF ImageDescription'),
            (b'Software', 'TIFF Software'),
            (b'HostComputer', 'TIFF HostComputer'),
            (b'Artist', 'TIFF Artist'),
            (b'Copyright', 'TIFF Copyright'),
            (b'DocumentName', 'TIFF DocumentName'),
        ]:
            if pat in haystack:
                return f"TIFF metadata found: {name}"
        # Structural check: walk the IFD chain and fail on any surviving
        # known metadata tag ID (Make, Model, Software, EXIF/GPS pointers...).
        try:
            if magic == 42:
                ifd_offset = struct.unpack(order + 'I', data[4:8])[0]
                entry_size, next_len = 12, 4
            else:
                ifd_offset = struct.unpack(order + 'Q', data[8:16])[0]
                entry_size, next_len = 20, 8
        except struct.error:
            return None
        known_tags = TIFF_METADATA_TAGS
        current = ifd_offset
        visited = set()
        while 8 <= current < len(data) - 2:
            if current in visited:
                break
            visited.add(current)
            try:
                num = struct.unpack(order + 'H', data[current:current+2])[0]
            except struct.error:
                break
            for i in range(num):
                entry = current + 2 + i * entry_size
                if entry + entry_size > len(data):
                    break
                try:
                    tag = struct.unpack(order + 'H', data[entry:entry+2])[0]
                except struct.error:
                    continue
                if tag in known_tags:
                    return f"TIFF metadata tag survives: 0x{tag:04X}"
            next_off = current + 2 + num * entry_size
            if next_off + next_len > len(data):
                break
            try:
                current = struct.unpack(
                    order + ('Q' if magic == 43 else 'I'),
                    data[next_off:next_off + next_len])[0]
            except struct.error:
                break
            if current == 0:
                break
        return None

    @staticmethod
    def _verify_gif_structure(data: bytes) -> Optional[str]:
        """Verify a GIF has no comment extension blocks (0x21 0xFE)."""
        if len(data) < 6 or data[:3] not in (b'GIF', b'gif'):
            return None
        n = len(data)
        pos = 13
        packed = data[10]
        if packed & 0x80:
            pos += 3 * (1 << ((packed & 0x07) + 1))
        while pos < n - 1:
            b = data[pos]
            if b == 0x3B:
                break
            if b == 0x21 and pos + 1 < n and data[pos + 1] == 0xFE:
                return "GIF comment extension block found"
            if b == 0x2C:
                pos += 10
                img_packed = data[pos - 1]
                if img_packed & 0x80:
                    pos += 3 * (1 << ((img_packed & 0x07) + 1))
                pos += 1
                while pos < n and data[pos] != 0:
                    pos += 1 + data[pos]
                pos += 1
                continue
            if b == 0x21:
                pos += 2
                while pos < n and data[pos] != 0:
                    pos += 1 + data[pos]
                pos += 1
                continue
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
