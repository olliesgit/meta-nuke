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

from meta_nuke import MetaNuke  # noqa: E402


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
    content += ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
    content += ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    content += ' width="100" height="100">\n'
    content += '  <metadata>'
    content += '<rdf:RDF><rdf:Description>'
    content += '<dc:creator>leaky_author</dc:creator>'
    content += '</rdf:Description></rdf:RDF></metadata>\n'
    content += '  <desc>A description that should not survive</desc>\n'
    content += '  <title>My Leaky SVG</title>\n'
    content += '  <rect width="100" height="100" fill="blue"/>\n'
    content += '</svg>\n'
    path.write_text(content)


def has_svg_metadata(data: str) -> bool:
    """Return True if SVG contains metadata/desc/title elements."""
    return ('<metadata>' in data or '<desc>' in data or '<title>' in data
            or '<!--' in data or '<?xml' in data)


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
    from meta_nuke import _log_results
    log_path = tmp / "nuke.log"
    results = [("/tmp/a.jpg", True, "NUKED: a.jpg"), ("/tmp/b.png", False, "FAIL")]
    _log_results(str(log_path), results)
    check("log file created", log_path.exists())
    if log_path.exists():
        content = log_path.read_text()
        check("log has total count", 'total=2' in content)
        check("log has OK/FAIL", 'OK' in content and 'FAIL' in content)


def test_banner_constants(_=None):
    """Test that the BANNER constant is defined and looks right."""
    print("test_banner_constants")
    from meta_nuke import BANNER
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
    from meta_nuke import _collect_files
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
            test_banner_constants,
            test_collect_files_recursive,
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
