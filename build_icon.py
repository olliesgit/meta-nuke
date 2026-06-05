"""Generate the Meta Nuke macOS app icon.

Builds a 1024x1024 master with a macOS-style rounded-square (squircle)
background, subtle dark gradient, dark-red edge ring, and a radiation
trefoil centred on it. Writes every required size to the iconset and
rebuilds MetaNuke.icns via `iconutil`.

Run:    venv/bin/python build_icon.py
"""
import math
import os
import subprocess
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
APP_RES = os.path.join(HERE, 'Meta Nuke.app', 'Contents', 'Resources')
ICNSET = os.path.join(APP_RES, 'MetaNuke.iconset')
ICNS   = os.path.join(APP_RES, 'MetaNuke.icns')
PNG    = os.path.join(APP_RES, 'MetaNuke.png')

SIZES = {
    'icon_16x16.png':      16,
    'icon_16x16@2x.png':   32,
    'icon_32x32.png':      32,
    'icon_32x32@2x.png':   64,
    'icon_128x128.png':    128,
    'icon_128x128@2x.png': 256,
    'icon_256x256.png':    256,
    'icon_256x256@2x.png': 512,
    'icon_512x512.png':    512,
    'icon_512x512@2x.png': 1024,
}

BASE = 1024
CORNER_RADIUS = int(BASE * 0.225)  # macOS squircle radius

# Theme colours (match the app)
BG_TOP    = (26, 12, 12, 255)
BG_BOTTOM = (8,  2,  2,  255)
EDGE_RED  = (139, 0, 0, 255)
RING_YEL  = (255, 214, 10, 255)
RING_ORG  = (255, 122, 0, 255)
CENTER_BG = (5, 5, 5, 255)
BLADE     = (255, 214, 10, 255)


def make_base_icon():
    img = Image.new('RGBA', (BASE, BASE), (0, 0, 0, 0))

    # 1. Squircle background with vertical gradient
    gradient = Image.new('RGBA', (BASE, BASE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(BASE):
        t = y / (BASE - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        gd.line([(0, y), (BASE, y)], fill=(r, g, b, 255))

    mask = Image.new('L', (BASE, BASE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, BASE - 1, BASE - 1],
        radius=CORNER_RADIUS,
        fill=255,
    )
    img.paste(gradient, (0, 0), mask)

    # 2. Subtle dark-red edge ring just inside the squircle
    edge = int(BASE * 0.018)
    ring = Image.new('RGBA', (BASE, BASE), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.rounded_rectangle(
        [edge, edge, BASE - edge - 1, BASE - edge - 1],
        radius=CORNER_RADIUS - edge,
        outline=EDGE_RED,
        width=int(BASE * 0.012),
    )
    img.alpha_composite(ring)

    # 3. Radiation trefoil, centred
    cx, cy = BASE // 2, BASE // 2
    R = int(BASE * 0.34)

    trefoil = Image.new('RGBA', (BASE, BASE), (0, 0, 0, 0))
    td = ImageDraw.Draw(trefoil)

    td.ellipse(
        [cx - R, cy - R, cx + R, cy + R],
        outline=RING_YEL, width=int(BASE * 0.022),
    )

    r2 = int(R * 0.86)
    td.ellipse(
        [cx - r2, cy - r2, cx + r2, cy + r2],
        outline=RING_ORG, width=int(BASE * 0.075),
    )

    blade_len = int(R * 0.66)
    blade_w   = int(R * 0.22)
    for i in range(3):
        ang = math.radians(i * 120 - 90)
        tip = (cx + int(blade_len * math.cos(ang)),
               cy + int(blade_len * math.sin(ang)))
        perp = ang + math.pi / 2
        base1 = (cx + int(blade_w * math.cos(perp)),
                 cy + int(blade_w * math.sin(perp)))
        base2 = (cx - int(blade_w * math.cos(perp)),
                 cy - int(blade_w * math.sin(perp)))
        td.polygon([base1, tip, base2], fill=BLADE)

    r3 = int(R * 0.40)
    td.ellipse(
        [cx - r3, cy - r3, cx + r3, cy + r3],
        fill=CENTER_BG,
    )

    img.alpha_composite(trefoil)
    return img


def write_iconset(base_img):
    os.makedirs(ICNSET, exist_ok=True)
    for name, sz in SIZES.items():
        out = base_img.resize((sz, sz), Image.LANCZOS)
        out.save(os.path.join(ICNSET, name), 'PNG')
        print(f'  wrote {name}  ({sz}x{sz})')
    base_img.save(PNG, 'PNG')
    print(f'  wrote {os.path.basename(PNG)}  (1024x1024 master)')


def rebuild_icns():
    subprocess.run(['iconutil', '-c', 'icns', ICNSET, '-o', ICNS], check=True)
    print(f'  rebuilt {os.path.basename(ICNS)}')


if __name__ == '__main__':
    print('Building icon...')
    base = make_base_icon()
    print('Writing iconset...')
    write_iconset(base)
    print('Rebuilding .icns...')
    rebuild_icns()
    print('Done.')
