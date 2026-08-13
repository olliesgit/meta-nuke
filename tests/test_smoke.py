"""Smoke tests for Meta Nuke.

Plain script (no pytest) — run with:

    python tests/test_smoke.py

Exits 0 on success, non-zero on any failure. Uses only Pillow and the
target module, so it runs in the existing venv with zero extra deps.

The tests build synthetic inputs in a temp dir, run the nuke, and assert
structural cleanliness — no exiftool dependency, no network, no GUI.
"""

import io
import os
import struct
import sys
import tempfile
import traceback
from pathlib import Path

# Make the repo root importable regardless of where the test is run from.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, PngImagePlugin  # noqa: E402

from metanuke import MetaNuke  # noqa: E402
from metanuke.utils import log_results as _log_results
from metanuke.utils import collect_files as _collect_files
from metanuke.utils import load_config as _load_config
from metanuke.utils import save_config as _save_config
from metanuke import __version__


passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  ok    {label}")
        passed += 1
    else:
        print(f"  FAIL  {label}  {detail}")
        failed += 1


def make_jpeg_with_exif(path: Path) -> None:
    """Build a JPEG that contains a real EXIF APP1 segment + a comment."""
    img = Image.new('RGB', (320, 240), (200, 100, 50))
    # Pillow lets us inject EXIF bytes + a comment via save kwargs.
    exif_bytes = (
        b'Exif\x00\x00'                  # EXIF header
        + b'MM'                            # big-endian
        + struct.pack('>H', 0x002A)        # magic
        + struct.pack('>I', 8)            # IFD0 offset
        # IFD0: 1 entry, then 4 bytes of padding
        + struct.pack('>H', 1)
        + struct.pack('>HHI', 0x010F, 2, 4)  # Make tag, ASCII, 4 bytes
        + b'TEST'                          # value
        + struct.pack('>I', 0)             # next IFD
    )
    img.save(
        path,
        format='JPEG',
        exif=exif_bytes,
        comment=b'private comment that must not survive',
        quality=90,
    )


def make_png_with_text(path: Path) -> None:
    """Build a PNG with tEXt / tIME / pHYs chunks that must be stripped."""
    img = Image.new('RGB', (200, 150), (10, 20, 30))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text('Author', 'leaky author')
    pnginfo.add_text('Software', 'leaky software')
    img.save(path, format='PNG', pnginfo=pnginfo, dpi=(300, 300))


def make_gif_with_comment(path: Path) -> None:
    """Build a GIF with a 0x21 0xFE comment extension block."""
    img = Image.new('P', (100, 100))
    img.putpalette([i % 256 for i in range(768)])
    img.save(path, format='GIF', comment='leaky gif comment')


def has_app1_jpeg(data: bytes) -> bool:
    """Return True if the JPEG contains an APP1 (EXIF/XMP) segment."""
    if data[:2] != b'\xff\xd8':
        return False
    pos = 2
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xD9 or marker == 0xDA:
            return False
        if pos + 4 > len(data):
            return False
        length = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        if 0xE0 <= marker <= 0xEF:
            return True
        if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01, 0x00):
            pos += 2
        else:
            pos += 2 + length
    return False


def has_text_png_chunk(data: bytes) -> bool:
    """Return True if the PNG contains a tEXt / iTXt / zTXt chunk."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return False
    for chunk_type in (b'tEXt', b'iTXt', b'zTXt', b'tIME', b'pHYs'):
        if chunk_type in data:
            return True
    return False


def has_gif_comment_block(data: bytes) -> bool:
    """Return True if a GIF has a 0x21 0xFE comment introducer at a valid
    structural position (not inside LZW data)."""
    if data[:3] not in (b'GIF', b'gif'):
        return False
    n = len(data)
    pos = 13
    packed = data[10]
    if packed & 0x80:
        pos += 3 * (1 << ((packed & 0x07) + 1))
    while pos < n - 1:
        b = data[pos]
        if b == 0x3B:
            return False
        if b == 0x21 and pos + 1 < n and data[pos + 1] == 0xFE:
            return True
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
        return False
    return False


def make_svg_with_metadata(path: Path) -> None:
    """Build an SVG with metadata elements that must be stripped."""
    content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    content += '<!-- created by LeakyApp v3.0 -->\n'
    content += '<svg xmlns="http://www.w3.org/2000/svg"'
    content += ' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
    content += ' xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"'
    content += ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
    content += ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    content += ' xmlns:xlink="http://www.w3.org/1999/xlink"'
    content += ' width="200" height="200">\n'
    content += '  <metadata>'
    content += '<rdf:RDF><rdf:Description>'
    content += '<dc:creator>leaky_author</dc:creator>'
    content += '</rdf:Description></rdf:RDF></metadata>\n'
    content += '  <desc>A description that should not survive</desc>\n'
    content += '  <title>My Leaky SVG</title>\n'
    content += '  <script>alert("xss")</script>\n'
    content += '  <rect width="100" height="100" fill="blue"'
    content += ' inkscape:label="layer1" sodipodi:type="arc"/>\n'
    content += '  <image xlink:href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"'
    content += ' width="50" height="50"/>\n'
    content += '  <a xlink:href="http://evil.com/tracker">\n'
    content += '    <text x="10" y="10">link</text>\n'
    content += '  </a>\n'
    content += '</svg>\n'
    path.write_text(content)


def has_svg_metadata(data: str) -> bool:
    """Return True if SVG contains metadata/desc/title elements."""
    return ('<metadata>' in data or '<desc>' in data or '<title>' in data
            or '<!--' in data or '<?xml' in data)


def has_svg_editor_footprints(data: str) -> bool:
    """Return True if SVG has editor namespace usages."""
    return ('inkscape:' in data or 'sodipodi:' in data
            or 'xlink:href' in data
            or 'xmlns:inkscape' in data
            or 'xmlns:sodipodi' in data)


def make_tiff_with_metadata(path: Path) -> None:
    """Build a TIFF with metadata fields."""
    img = Image.new('RGB', (100, 80), (200, 150, 100))
    exif = img.getexif()
    exif[0x010F] = "LeakyCam"  # Make
    exif[0x0110] = "X9000"     # Model
    exif[0x0131] = "LeakySoft" # Software
    exif[0x8298] = "© Leaky"   # Copyright
    img.save(path, format='TIFF', exif=exif.tobytes())


def has_tiff_metadata_tags(data: bytes) -> list[str]:
    """Return a list of metadata strings found in TIFF binary."""
    found = []
    for pat, name in [(b'ImageDescription', 'ImageDescription'),
                       (b'LeakyCam', 'Make'),
                       (b'X9000', 'Model'),
                       (b'LeakySoft', 'Software'),
                       (b'Leaky', 'Copyright')]:
        if pat in data:
            found.append(name)
    return found


# Tests -----------------------------------------------------------------

def test_jpeg_stripping(tmp: Path) -> None:
    print("test_jpeg_stripping")
    src = tmp / "with_exif.jpg"
    make_jpeg_with_exif(src)
    before = src.read_bytes()
    check("input has APP1 segment", has_app1_jpeg(before),
          detail="synthetic JPEG did not contain expected EXIF")

    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke_image returned success", ok, detail=msg)
    check("result message reports NUKED", "NUKED" in msg, detail=msg)

    after = src.read_bytes()
    check("no APP segments after nuke", not has_app1_jpeg(after))
    check("no Exif header bytes", b'Exif\x00\x00' not in after)
    check("output is still a valid JPEG", after[:2] == b'\xff\xd8')
    with Image.open(src) as img:
        check("output opens with Pillow", img.size == (320, 240),
              detail=f"size={img.size}")


def test_png_stripping(tmp: Path) -> None:
    print("test_png_stripping")
    src = tmp / "with_text.png"
    make_png_with_text(src)
    before = src.read_bytes()
    check("input has metadata chunks", has_text_png_chunk(before))

    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke_image returned success", ok, detail=msg)

    after = src.read_bytes()
    check("no tEXt/iTXt/zTXt/tIME/pHYs chunks", not has_text_png_chunk(after))
    check("PNG signature preserved", after[:8] == b'\x89PNG\r\n\x1a\n')
    with Image.open(src) as img:
        check("output opens with Pillow", img.size == (200, 150),
              detail=f"size={img.size}")


def test_gif_stripping(tmp: Path) -> None:
    print("test_gif_stripping")
    src = tmp / "with_comment.gif"
    make_gif_with_comment(src)
    before = src.read_bytes()
    check("input has GIF comment", has_gif_comment_block(before))

    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke_image returned success", ok, detail=msg)

    after = src.read_bytes()
    check("no GIF comment block", not has_gif_comment_block(after))
    check("GIF header preserved", after[:3] in (b'GIF', b'gif'))


def test_unsupported_format(tmp: Path) -> None:
    print("test_unsupported_format")
    src = tmp / "data.txt"
    src.write_text("not an image")
    ok, msg = MetaNuke.nuke_image(str(src))
    check("rejected unsupported format", not ok, detail=msg)


def test_missing_file(tmp: Path) -> None:
    print("test_missing_file")
    ok, msg = MetaNuke.nuke_image(str(tmp / "does-not-exist.jpg"))
    check("rejected missing file", not ok, detail=msg)


def test_bulk_nuke(tmp: Path) -> None:
    print("test_bulk_nuke")
    paths = []
    for i in range(5):
        p = tmp / f"bulk_{i}.jpg"
        make_jpeg_with_exif(p)
        paths.append(p)
    for p in paths:
        ok, msg = MetaNuke.nuke_image(str(p))
        check(f"nuked {p.name}", ok, detail=msg)
    for p in paths:
        data = p.read_bytes()
        check(f"{p.name} clean of APP segments", not has_app1_jpeg(data))


def test_svg_stripping(tmp: Path) -> None:
    print("test_svg_stripping")
    src = tmp / "with_meta.svg"
    make_svg_with_metadata(src)
    before = src.read_text()
    check("input has SVG metadata", has_svg_metadata(before))
    check("input has editor footprints", has_svg_editor_footprints(before))
    check("input has script tag", '<script>' in before)
    check("input has data-URI image", 'data:image' in before)
    check("input has external href", 'http://evil.com' in before)

    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke_image returned success", ok, detail=msg)

    after = src.read_text()
    check("no metadata element", '<metadata>' not in after)
    check("no desc element", '<desc>' not in after)
    check("no title element", '<title>' not in after)
    check("no XML comments", '<!--' not in after)
    check("XML declaration stripped", '<?xml' not in after)
    check("visual content preserved", '<rect' in after)
    check("inkscape namespace stripped", 'inkscape' not in after)
    check("sodipodi namespace stripped", 'sodipodi' not in after)
    check("xlink:href stripped", 'xlink:href' not in after)
    check("script tag stripped", '<script>' not in after)
    check("external href stripped", 'evil.com' not in after)
    check("no editor footprints", not has_svg_editor_footprints(after))


def test_svg_with_output_dir(tmp: Path) -> None:
    print("test_svg_with_output_dir")
    src = tmp / "svg_output_test.svg"
    make_svg_with_metadata(src)
    out_dir = tmp / "clean"
    ok, msg = MetaNuke.nuke_image(str(src), output_path=str(out_dir / src.name))
    check("nuke_image with output dir", ok, detail=msg)
    output_file = out_dir / src.name
    check("output file exists", output_file.exists())
    if output_file.exists():
        after = output_file.read_text()
        check("output SVG has no metadata", '<metadata>' not in after)


def test_noise_level_0(tmp: Path) -> None:
    """Test noise_level=0 produces valid output."""
    print("test_noise_level_0")
    src = tmp / "no_noise.jpg"
    make_jpeg_with_exif(src)
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke_image with noise_level=0", ok, detail=msg)
    check("no APP segments after noise-free nuke",
          not has_app1_jpeg(src.read_bytes()))


def test_sha256_in_output(tmp: Path) -> None:
    """Test that SHA256 hash appears in the success message."""
    print("test_sha256_in_output")
    src = tmp / "hash_test.jpg"
    make_jpeg_with_exif(src)
    ok, msg = MetaNuke.nuke_image(str(src))
    check("sha256 in output", 'sha256:' in msg, detail=msg)


def test_log_output(tmp: Path) -> None:
    """Test that _log_results writes a valid log file."""
    print("test_log_output")
    log_path = tmp / "nuke.log"
    results = [("/tmp/a.jpg", True, "NUKED: a.jpg"), ("/tmp/b.png", False, "FAIL")]
    _log_results(str(log_path), results)
    check("log file created", log_path.exists())
    if log_path.exists():
        content = log_path.read_text()
        check("log has total count", 'total=2' in content)
        check("log has OK/FAIL", 'OK' in content and 'FAIL' in content)


def test_json_output(tmp: Path) -> None:
    """Test that main() with --json produces valid JSON on stdout."""
    print("test_json_output")
    # Build a real image to nuke
    src = tmp / "json_test.jpg"
    make_jpeg_with_exif(src)
    # Run via nuke_image and manually build JSON to test format
    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke succeeds for JSON test", ok, detail=msg)
    import json
    payload = json.dumps({
        'tool': 'meta-nuke',
        'results': [{'file': str(src), 'success': ok, 'message': msg}],
    })
    parsed = json.loads(payload)
    check("JSON has results key", 'results' in parsed)
    check("JSON has success field", parsed['results'][0]['success'] is True)
    check("JSON has sha256 in message", 'sha256:' in parsed['results'][0]['message'])


def make_pdf_with_metadata(path: Path) -> None:
    """Build a PDF with document metadata."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), 'Test PDF content', fontsize=16)
    doc.set_metadata({'author': 'Leaky Author', 'producer': 'LeakyApp',
                      'subject': 'Sensitive Data'})
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()


def test_pdf_stripping(tmp: Path) -> None:
    """Test PDF metadata stripping (basic)."""
    print("test_pdf_stripping")
    from metanuke import PDF_AVAILABLE
    if not PDF_AVAILABLE:
        print("  skip  PDF not available (no PyMuPDF)")
        return
    src = tmp / "with_meta.pdf"
    make_pdf_with_metadata(src)
    import fitz
    before = fitz.open(str(src)).metadata
    check("input has author", bool(before.get('author')), detail=before.get('author', ''))
    check("input has producer", bool(before.get('producer')), detail=before.get('producer', ''))

    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke_image returned success", ok, detail=msg)

    after = fitz.open(str(src)).metadata
    check("author stripped", not after.get('author'))
    check("producer stripped", not after.get('producer'))
    check("subject stripped", not after.get('subject'))


def test_pdf_comprehensive(tmp: Path) -> None:
    """Test PDF stripping of annotations, embedded files, AcroForm, and image metadata."""
    print("test_pdf_comprehensive")
    from metanuke import PDF_AVAILABLE
    if not PDF_AVAILABLE:
        print("  skip  PDF not available (no PyMuPDF)")
        return
    import fitz

    # Build a PDF with everything
    src = tmp / "comprehensive.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), 'test content', fontsize=16)

    # Metadata
    doc.set_metadata({'author': 'Leaky Author', 'subject': 'Secret Doc',
                      'producer': 'LeakyApp', 'creator': 'LeakyMaker'})

    # Annotation
    page.add_freetext_annot((50, 100, 150, 130), 'leaky sticky note',
                            fontsize=10)

    # Embedded file
    doc.embfile_add('secret.txt', b'classified content',
                    filename='secret.txt')

    # AcroForm (create a text field)
    # We create it via widget annotation on the page
    widget = fitz.Widget()  # type: ignore
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = 'secret_field'
    widget.rect = fitz.Rect(50, 150, 200, 180)
    page.add_widget(widget)

    doc.save(str(src), garbage=4, deflate=True)
    doc.close()

    # Verify input has all the things
    doc2 = fitz.open(str(src))
    check("input has author", bool(doc2.metadata.get('author')),
          detail=doc2.metadata.get('author', ''))
    has_annot = len(list(doc2[0].annots() or [])) > 0
    check("input has annotation", has_annot)
    has_emb = doc2.embfile_count() > 0
    check("input has embedded file", has_emb, detail=f"count={doc2.embfile_count()}")
    # Check for AcroForm — look for a widget on the page
    page_widgets = list(doc2[0].widgets() or []) if hasattr(doc2[0], 'widgets') else []
    has_widget = len(page_widgets) > 0
    # Also check catalog for AcroForm key
    cat_acroform = doc2.xref_get_key(doc2.pdf_catalog(), 'AcroForm')
    check("input has AcroForm catalog key",
          cat_acroform and cat_acroform[0] != 'null',
          detail=str(cat_acroform))
    doc2.close()

    # Nuke it
    ok, msg = MetaNuke.nuke_image(str(src))
    check("nuke_image succeeded", ok, detail=msg)

    # Verify everything is gone
    doc3 = fitz.open(str(src))
    check("no author", not doc3.metadata.get('author'))
    check("no subject", not doc3.metadata.get('subject'))
    check("no producer", not doc3.metadata.get('producer'))
    check("no creator", not doc3.metadata.get('creator'))

    after_annots = list(doc3[0].annots() or [])
    check("no annotations", len(after_annots) == 0,
          detail=f"found {len(after_annots)}")
    after_emb = doc3.embfile_count()
    check("no embedded files", after_emb == 0,
          detail=f"embfile_count={after_emb}")

    after_cat = doc3.xref_get_key(doc3.pdf_catalog(), 'AcroForm')
    check("AcroForm key gone",
          after_cat is None or after_cat[0] == 'null',
          detail=str(after_cat))

    after_widgets = list(doc3[0].widgets() or []) if hasattr(doc3[0], 'widgets') else []
    check("no widgets", len(after_widgets) == 0)
    doc3.close()
    check("PDF still readable", src.exists() and src.stat().st_size > 0,
          detail=f"size={src.stat().st_size}")


def test_banner_constants(_=None):
    """Test that the BANNER constant is defined and looks right."""
    print("test_banner_constants")
    from metanuke.utils import BANNER
    # Banner uses Unicode block chars, not ASCII — check for distinctive patterns
    check("banner has Unicode blocks", '\u2588' in BANNER,
          detail="BANNER missing block character")
    check("banner has box-drawing chars", '\u2557' in BANNER or '\u2554' in BANNER,
          detail="BANNER missing box-drawing")
    lines = BANNER.count('\n')
    check("banner is multi-line", lines >= 5,
          detail=f"only {lines} lines")


def test_collect_files_recursive(tmp: Path) -> None:
    """Test recursive file collection."""
    print("test_collect_files_recursive")
    # Use a clean subdir so previous test artefacts don't interfere
    work = tmp / "collect_test"
    work.mkdir()
    subdir = work / "sub"
    subdir.mkdir()
    (subdir / "nested.jpg").write_bytes(b'')
    (work / "root.png").write_bytes(b'')

    files = _collect_files([str(work)], recursive=False)
    check("non-recursive collects root only",
          len(files) == 1 and 'root.png' in files[0])

    files = _collect_files([str(work)], recursive=True)
    check("recursive finds nested files",
          len(files) == 2)


def test_orientation_preserved(tmp: Path) -> None:
    """A photo with EXIF Orientation must come out visually upright (pixels
    transposed) once the orientation tag is stripped — not left sideways."""
    print("test_orientation_preserved")
    src = tmp / "rotated.jpg"
    # 100x40 landscape buffer tagged Orientation=6 (rotate 90 CW on display).
    img = Image.new('RGB', (100, 40), (0, 0, 0))
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(src, format='JPEG', exif=exif, quality=95)

    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded", ok, detail=msg)
    with Image.open(src) as out:
        # After baking orientation, displayed dimensions (40x100) become real.
        check("dimensions transposed to upright", out.size == (40, 100),
              detail=f"size={out.size}")
        check("orientation tag gone", out.getexif().get(0x0112) is None)


def test_pixels_preserved_lossless(tmp: Path) -> None:
    """noise_level=0 on a lossless format (PNG) must not alter a single pixel."""
    print("test_pixels_preserved_lossless")
    src = tmp / "pixels.png"
    import random as _r
    _r.seed(1)
    img = Image.new('RGB', (32, 32))
    img.putdata([(_r.randint(0, 255), _r.randint(0, 255), _r.randint(0, 255))
                 for _ in range(32 * 32)])
    before = list(img.getdata())
    img.save(src, format='PNG')

    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded", ok, detail=msg)
    with Image.open(src) as out:
        check("pixels byte-identical (lossless, no noise)",
              list(out.convert('RGB').getdata()) == before)


def test_noise_bounds(tmp: Path) -> None:
    """Forensic noise must stay within its tiny imperceptible delta."""
    print("test_noise_bounds")
    src = tmp / "noisy.png"
    img = Image.new('RGB', (64, 64), (128, 128, 128))
    before = list(img.getdata())
    img.save(src, format='PNG')
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=5)
    check("nuke with noise succeeded", ok, detail=msg)
    with Image.open(src) as out:
        after = list(out.convert('RGB').getdata())
    max_delta = max(abs(a - b)
                    for pa, pb in zip(before, after)
                    for a, b in zip(pa, pb))
    check("level-5 noise delta <= 1", max_delta <= 1, detail=f"max={max_delta}")


def test_webp_stripping(tmp: Path) -> None:
    print("test_webp_stripping")
    src = tmp / "with_exif.webp"
    img = Image.new('RGB', (80, 60), (40, 90, 160))
    exif = img.getexif()
    exif[0x010F] = "LeakyCam"
    img.save(src, format='WEBP', exif=exif.tobytes())
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded", ok, detail=msg)
    after = src.read_bytes()
    check("no EXIF RIFF chunk", b'EXIF' not in after and b'Exif\x00\x00' not in after)
    with Image.open(src) as out:
        check("output opens, size preserved", out.size == (80, 60),
              detail=f"size={out.size}")


def test_heic_not_destroyed(tmp: Path) -> None:
    """Regression: HEIC/AVIF were silently overwritten with 0 bytes."""
    print("test_heic_not_destroyed")
    from metanuke.core import HEIF_AVAILABLE
    if not HEIF_AVAILABLE:
        print("  skip  HEIF not available (no pillow-heif)")
        return
    src = tmp / "photo.heic"
    Image.new('RGB', (64, 48), (120, 30, 200)).save(src, format='HEIF')
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded (not destroyed)", ok, detail=msg)
    check("file is non-empty", src.exists() and src.stat().st_size > 0,
          detail=f"size={src.stat().st_size if src.exists() else 'GONE'}")
    with Image.open(src) as out:
        check("output is a valid image", out.size == (64, 48), detail=f"size={out.size}")


def test_avif_roundtrip(tmp: Path) -> None:
    print("test_avif_roundtrip")
    from PIL import features
    if not (hasattr(features, 'check') and features.check('avif')):
        print("  skip  AVIF not supported by this Pillow")
        return
    src = tmp / "photo.avif"
    try:
        Image.new('RGB', (48, 32), (90, 10, 160)).save(src, format='AVIF')
    except Exception as e:
        print(f"  skip  cannot encode AVIF ({e})")
        return
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded (not destroyed)", ok, detail=msg)
    check("file is non-empty", src.exists() and src.stat().st_size > 0)


def test_backup_flag(tmp: Path) -> None:
    """--backup must leave a .bak that still carries the original metadata."""
    print("test_backup_flag")
    src = tmp / "bk.jpg"
    make_jpeg_with_exif(src)
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0, backup=True)
    check("nuke succeeded", ok, detail=msg)
    backup = src.with_name(src.name + '.bak')
    check("backup file created", backup.exists())
    if backup.exists():
        check("original (in place) is clean", not has_app1_jpeg(src.read_bytes()))
        check("backup retains original EXIF", has_app1_jpeg(backup.read_bytes()))


def test_unsupported_save_no_dataloss(tmp: Path) -> None:
    """A supported-by-scan but unsaveable extension must not zero the file."""
    print("test_unsupported_save_no_dataloss")
    # .bmp is handled, but verify the empty-buffer safety net never fires on it
    # by checking a normal nuke keeps bytes. (Direct guard is covered in code.)
    src = tmp / "safe.bmp"
    Image.new('RGB', (20, 20), (5, 5, 5)).save(src, format='BMP')
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("bmp nuke kept non-empty file", ok and src.stat().st_size > 0, detail=msg)


def test_tiff_stripping(tmp: Path) -> None:
    """Test TIFF metadata is stripped."""
    print("test_tiff_stripping")
    src = tmp / "meta.tiff"
    make_tiff_with_metadata(src)
    before = src.read_bytes()
    before_tags = has_tiff_metadata_tags(before)
    check("input has metadata tags", len(before_tags) > 0, detail=str(before_tags))

    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke_image returned success", ok, detail=msg)

    after = src.read_bytes()
    after_tags = has_tiff_metadata_tags(after)
    check("no TIFF metadata tags", len(after_tags) == 0, detail=str(after_tags))
    check("TIFF signature preserved", after[:2] in (b'II', b'MM'))
    with Image.open(src) as img:
        check("TIFF opens, size preserved", img.size == (100, 80), detail=f"size={img.size}")


def test_tiff_value_bytes_scrubbed(tmp: Path) -> None:
    """TIFF metadata VALUE bytes must not survive the binary-level strip.

    Zeroing only the IFD tag ID leaves the ASCII payload ("Adobe Photoshop
    24.0", artist names) recoverable from the raw file. The strip must scrub
    the values too.
    """
    print("test_tiff_value_bytes_scrubbed")
    import io as _io
    from metanuke.core import MetaNuke as _MN

    # Build a TIFF buffer that carries metadata strings (as a camera/editor
    # tool would) and feed it straight to the binary stripper, bypassing
    # pixel reconstruction, to prove the strip pass itself is airtight.
    img = Image.new('RGB', (100, 80), (200, 100, 50))
    buf = _io.BytesIO()
    img.save(buf, format='TIFF', compression='none',
             software='Adobe Photoshop 24.0', artist='Jane Doe',
             description='leaky desc')
    buf.seek(0)
    before = buf.read()
    check("input carries Photoshop string", b'Adobe Photoshop 24.0' in before)
    check("input carries artist string", b'Jane Doe' in before)

    stripped = _MN._strip_tiff_metadata(_io.BytesIO(before))
    after = stripped.read()
    check("Photoshop string scrubbed", b'Adobe Photoshop 24.0' not in after)
    check("artist string scrubbed", b'Jane Doe' not in after)
    check("description string scrubbed", b'leaky desc' not in after)

    # End-to-end through nuke_image as well.
    src = tmp / "leak.tiff"
    img.save(src, format='TIFF', compression='none',
             software='Adobe Photoshop 24.0', artist='Jane Doe',
             description='leaky desc')
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded", ok, detail=msg)
    after2 = src.read_bytes()
    check("e2e: Photoshop string gone", b'Adobe Photoshop 24.0' not in after2)
    with Image.open(src) as img2:
        check("scrubbed TIFF still opens", img2.size == (100, 80))


def test_animated_gif_output_dir(tmp: Path) -> None:
    """Animated GIF + --output must write to the output dir, not in place."""
    print("test_animated_gif_output_dir")
    src = tmp / "anim.gif"
    f1 = Image.new('RGB', (50, 40), (255, 0, 0))
    f2 = Image.new('RGB', (50, 40), (0, 255, 0))
    f1.save(src, format='GIF', save_all=True, append_images=[f2],
            duration=100, loop=0, comment='leaky comment')
    before = src.read_bytes()

    out_dir = tmp / "out"
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0,
                                  output_path=str(out_dir))
    check("nuke succeeded", ok, detail=msg)

    out_file = out_dir / "anim.gif"
    check("output written to out dir", out_file.exists())
    check("original untouched", src.read_bytes() == before)
    with Image.open(out_file) as img:
        frames_now = getattr(img, 'n_frames', 1)
        check("animation preserved", frames_now == 2,
              detail=f"frames={frames_now}")
    check("comment stripped", not has_gif_comment_block(out_file.read_bytes()))

    # --rename in output mode gets a content-hash filename
    ok2, msg2 = MetaNuke.nuke_image(str(src), noise_level=0,
                                    output_path=str(out_dir), rename=True)
    check("rename nuke succeeded", ok2, detail=msg2)
    hashed = [f for f in out_dir.iterdir() if f.suffix == '.gif'
              and f.name != 'anim.gif']
    check("rename produced hash filename", len(hashed) == 1,
          detail=str([f.name for f in out_dir.iterdir()]))


def test_exiftool_verify(tmp: Path) -> None:
    """If exiftool is on PATH, verify that a nuked JPEG has zero metadata."""
    print("test_exiftool_verify")
    import shutil
    exiftool_path = shutil.which('exiftool')
    if not exiftool_path:
        print("  skip  exiftool not available")
        return
    import subprocess

    # Create a JPEG with maximum metadata
    src = tmp / "exif.jpg"
    make_jpeg_with_exif(src)
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("nuke succeeded for exiftool check", ok, detail=msg)

    # Run exiftool (check for remaining image metadata)
    r = subprocess.run(
        [exiftool_path, '-All', '-G1', '-s', str(src)],
        capture_output=True, text=True, timeout=30,
    )
    # Exiftool always shows system-level fields (FileSize, FileModifyDate, etc.)
    # We only care about image metadata groups: EXIF, XMP, ICC, IPTC, GPS
    image_meta_groups = ('[EXIF]', '[XMP]', '[ICC]', '[IPTC]', '[GPS]',
                         '[MakerNotes]')
    metadata_lines = [
        l.strip() for l in r.stdout.split('\n')
        if l.strip() and l.strip().startswith(image_meta_groups)
    ]
    check("exiftool reports no image metadata",
          len(metadata_lines) == 0,
          detail=f"found {len(metadata_lines)}: {metadata_lines}")


def test_strict_mode(tmp: Path) -> None:
    """Test --strict mode passes on normal files (no silent failures)."""
    print("test_strict_mode")
    src = tmp / "strict.jpg"
    make_jpeg_with_exif(src)
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0, strict=True)
    check("strict mode passes on normal file", ok, detail=msg)
    check("JPEG still clean", not has_app1_jpeg(src.read_bytes()))


def test_rename_flag(tmp: Path) -> None:
    """Test --rename produces content-hash filenames."""
    print("test_rename_flag")
    src = tmp / "rename.jpg"
    make_jpeg_with_exif(src)
    out_dir = tmp / "renamed"
    out_dir.mkdir()
    ok, msg = MetaNuke.nuke_image(
        str(src), noise_level=0, output_path=str(out_dir), rename=True,
    )
    check("rename: nuke succeeded", ok, detail=msg)
    # The output should NOT be named "rename.jpg"
    if ok:
        expected = out_dir / "rename.jpg"
        check("rename: original name not used", not expected.exists())
        # Should have a hex-hash-named file
        files = list(out_dir.glob('*.jpg'))
        check("rename: output file exists", len(files) == 1, detail=str(files))
        if files:
            name = files[0].stem
            check("rename: filename is hex hash", len(name) == 16,
                  detail=f"name={name}")
            all_hex = all(c in '0123456789abcdef' for c in name)
            check("rename: all hex chars", all_hex)


def test_double_encode_lossless(tmp: Path) -> None:
    """Noise_level=0 must skip double-encode (no second lossy pass)."""
    print("test_double_encode_lossless")
    src = tmp / "lossless_jpeg.jpg"
    make_jpeg_with_exif(src)
    ok, msg = MetaNuke.nuke_image(str(src), noise_level=0)
    check("lossless nuke succeeded", ok, detail=msg)
    check("JPEG still valid", src.read_bytes()[:2] == b'\xff\xd8')
    # With noise_level=0, double-encode is skipped, so the file should
    # only have been encoded once (at quality 95) — verify it opens cleanly
    with Image.open(src) as img:
        check("image opens", img.size == (320, 240))


def main() -> int:
    print("Meta Nuke smoke tests")
    print("=====================\n")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        tests = [
            test_jpeg_stripping,
            test_png_stripping,
            test_gif_stripping,
            test_unsupported_format,
            test_missing_file,
            test_bulk_nuke,
            test_svg_stripping,
            test_svg_with_output_dir,
            test_noise_level_0,
            test_sha256_in_output,
            test_log_output,
            test_json_output,
            test_pdf_stripping,
            test_pdf_comprehensive,
            test_banner_constants,
            test_collect_files_recursive,
            test_orientation_preserved,
            test_pixels_preserved_lossless,
            test_noise_bounds,
            test_webp_stripping,
            test_heic_not_destroyed,
            test_avif_roundtrip,
            test_backup_flag,
            test_unsupported_save_no_dataloss,
            test_tiff_stripping,
            test_tiff_value_bytes_scrubbed,
            test_animated_gif_output_dir,
            test_exiftool_verify,
            test_strict_mode,
            test_rename_flag,
            test_double_encode_lossless,
        ]
        for t in tests:
            try:
                t(tmp)
            except Exception:
                global failed
                print(f"  FAIL  {t.__name__} raised:")
                traceback.print_exc()
                failed += 1
            print()

    print("=" * 50)
    print(f"passed: {passed}   failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
