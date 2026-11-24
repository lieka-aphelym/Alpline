"""Draw the Alpline logo and icons from one geometry, so every file matches.

    python tools/make_brand.py          (needs playwright + Pillow; only after changing the logo)
    python tools/render_logo_frames.py  (afterwards: the launcher's animation frames)

The logo is an edelweiss that is also a propeller: three large offset petals (the blades), three small open
chevrons between them (the signal) and a diamond heart. Below about 40 px the chevrons are left out and the petals
get a little wider, so the flower still reads at 16 px.

Writes into viewer/brand/: logo-dark.svg, logo-light.svg, icon.svg (red square), icon-dark.svg (black square),
logo-dark-<n>.png, icon-<n>.png, icon-maskable-512.png, icon.ico; and the flower used by the pages (the FLOWER line
in viewer/js/core/theme.js, coloured by the theme and animated by viewer/css/theme.css).
"""
import io
import math
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "viewer" / "brand"
THEME_JS = ROOT / "viewer" / "js" / "core" / "theme.js"
WHITE, BLACK, YELLOW, RED = "#ffffff", "#0a0c0f", "#ffd60a", "#d52b1e"


def _pt(a_deg, x, y, cx=32.0, cy=32.0):
    a = math.radians(a_deg)
    return cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)


def petal(a, r0, r, w, skew):
    """A sharp petal pointing up from the centre, turned by a degrees; skew moves its tip sideways (the spin)."""
    m = r0 + (r - r0) * 0.42
    pts = [_pt(a, x, y) for x, y in ((0, -r0), (w, -m), (skew, -r), (-w, -m))]
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"


def geometry(small=False, scale=1.0):
    """The flower's parts: big petals, small chevrons (none when small), heart half-size. scale: for the icon."""
    big = [petal(a, 6 * scale, 30 * scale, (10 if small else 8) * scale, (8 if small else 9) * scale) for a in (0, 120, 240)]
    chev = [] if small else [(a, f"M{32 - 5 * scale:.2f} {32 - 12 * scale:.2f} L{32 + 2 * scale:.2f} {32 - 20 * scale:.2f} "
                                f"L{32 + 5 * scale:.2f} {32 - 12 * scale:.2f}") for a in (60, 180, 300)]
    return big, chev, (6 if small else 5) * scale


def heart(r, fill, cls=""):
    """The diamond heart, drawn as a path (not a turned square: a CSS animation would replace that turn)."""
    c, d = f' class="{cls}"' if cls else "", r * math.sqrt(2)
    return f'<path{c} d="M32 {32 - d:.2f} L{32 + d:.2f} 32 L32 {32 + d:.2f} L{32 - d:.2f} 32 Z" fill="{fill}"/>'


def svg(petals, mark, bg=None, small=False, scale=1.0):
    big, chev, r = geometry(small, scale)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">']
    if bg:
        out.append(f'<rect width="64" height="64" fill="{bg}"/>')
    out += [f'<path d="{d}" fill="{petals}"/>' for d in big]
    sw = 2.4 * scale
    out += [f'<path d="{d}" transform="rotate({a} 32 32)" fill="none" stroke="{petals}" stroke-width="{sw:.2f}" '
            f'stroke-linecap="square"/>' for a, d in chev]
    out.append(heart(r, mark))
    out.append("</svg>")
    return "".join(out)


def flower_js():
    """The page version: petals in the theme's text colour, chevrons as the three waves (lg-w0..2), heart in the
    accent colour. Each chevron sits in a turned group so the animation can move it along its own direction."""
    big, chev, r = geometry()
    parts = ['<g class="lg-sw">'] + [f'<path d="{d}" style="fill:var(--t-fg)"/>' for d in big]
    for i, (a, d) in enumerate(chev):
        parts.append(f'<g transform="rotate({a} 32 32)"><path class="lg-ch lg-w{i}" style="--dy:-4px;stroke:var(--t-fg);fill:none" d="{d}" '
                     f'stroke-width="2.4" stroke-linecap="square"/></g>')
    parts.append("</g>")
    parts.append(heart(r, "var(--t-acc)", "lg-hub").replace('fill="var(--t-acc)"', 'style="fill:var(--t-acc)"'))
    return "".join(parts)


def write_flower_into_theme_js():
    s = THEME_JS.read_text(encoding="utf-8")
    new, n = re.subn(r"^  var FLOWER = '.*';$", lambda _: f"  var FLOWER = '{flower_js()}';", s, count=1, flags=re.M)
    if n != 1:
        raise SystemExit("theme.js: the line `  var FLOWER = '...';` was not found")
    THEME_JS.write_text(new, encoding="utf-8", newline="\n")


def rasterise(jobs):
    """jobs: [(svg text, size, output path)]: drawn by Chromium (the same renderer as the pages)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        for text, n, out in jobs:
            pg = b.new_page(viewport={"width": n, "height": n}, device_scale_factor=1)
            sized = text.replace("<svg ", f"<svg width={n} height={n} ", 1)
            pg.set_content(f'<html><body style="margin:0;background:transparent">{sized}</body></html>')
            out.write_bytes(pg.screenshot(omit_background=True))
            pg.close()
        b.close()


def main():
    files = {
        "logo-dark.svg": svg(WHITE, YELLOW),
        "logo-light.svg": svg(BLACK, RED),
        "icon.svg": svg(WHITE, YELLOW, RED, small=True, scale=0.9),            # the tab icon: 16-32 px
        "icon-dark.svg": svg(WHITE, YELLOW, BLACK, small=True, scale=0.9),
    }
    for name, text in files.items():
        (BRAND / name).write_text(text + "\n", encoding="utf-8", newline="\n")
    jobs = [(svg(WHITE, YELLOW, small=n < 40), n, BRAND / f"logo-dark-{n}.png") for n in (24, 32, 40, 48, 64, 96, 128)]
    jobs += [(svg(WHITE, YELLOW, RED, small=n < 40, scale=0.9), n, BRAND / f"icon-{n}.png") for n in (16, 32, 48, 64, 128, 192, 256, 512)]
    # maskable: launchers crop to a circle or a rounded square, so the flower keeps inside the middle 80 %
    jobs.append((svg(WHITE, YELLOW, RED, scale=0.72), 512, BRAND / "icon-maskable-512.png"))
    rasterise(jobs)
    # the Windows icon: the small sizes from their own drawings (not scaled down from 256)
    ico_src = {n: Image.open(io.BytesIO((BRAND / f"icon-{n}.png").read_bytes())).convert("RGBA") for n in (16, 32, 48, 64, 128, 256)}
    ico_src[256].save(BRAND / "icon.ico", sizes=[(n, n) for n in sorted(ico_src)],
                      append_images=[ico_src[n] for n in sorted(ico_src) if n != 256])
    write_flower_into_theme_js()
    print("written:", ", ".join(sorted(files)), "+", len(jobs), "png, icon.ico, theme.js FLOWER")


if __name__ == "__main__":
    main()
