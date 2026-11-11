"""Render the launcher's logo animation frames from the web logo (viewer/js/core/theme.js + viewer/css/theme.css), so both match.

    python tools/render_logo_frames.py        (needs playwright + Pillow; only after changing the logo or its animation)

Writes viewer/brand/anim-intro-<size>.png and anim-busy-<size>.png: one horizontal strip of square frames each.
The launcher plays them (intro once at start, busy while it works). Frame timing is in FRAMES below and in launcher.pyw.
"""
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "viewer" / "brand"
SIZES = (24, 32, 40, 48, 64, 96)
FRAMES = {"intro": (30, 60), "busy": (20, 70)}     # frames, ms per frame (intro 1.8 s once, busy 1.4 s loop)
PAGE = """<!doctype html><html data-theme="dark"><head><link rel="stylesheet" href="{v}/css/theme.css"><script src="{v}/js/core/theme.js"></script>
<style>html,body{{margin:0;padding:0;background:transparent!important}} svg.logo{{width:{n}px;height:{n}px;display:block;
--t-fg:#ffffff;--t-acc:#ffd60a}}</style></head><body><span data-logo></span></body></html>"""


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        for n in SIZES:
            for kind, (count, ms) in FRAMES.items():
                f = BRAND / f"_page_{n}.html"
                f.write_text(PAGE.format(v=(ROOT / "viewer").as_uri(), n=n), encoding="utf-8")
                pg = b.new_page(viewport={"width": n, "height": n}, device_scale_factor=1)
                pg.goto(f.as_uri())
                pg.wait_for_selector("svg.logo")
                if kind == "busy":
                    pg.evaluate("document.querySelector('svg.logo').classList.remove('lg-intro'); alpBusy(true)")
                strip = Image.new("RGBA", (n * count, n))
                for i in range(count):
                    pg.evaluate(f"document.getAnimations().forEach(a => {{ a.pause(); a.currentTime = {i * ms}; }})")
                    shot = BRAND / "_frame.png"
                    pg.screenshot(path=str(shot), omit_background=True)
                    strip.paste(Image.open(shot), (i * n, 0))
                strip.save(BRAND / f"anim-{kind}-{n}.png", optimize=True)
                pg.close()
                f.unlink()
        (BRAND / "_frame.png").unlink(missing_ok=True)
        b.close()
    print("written:", ", ".join(f"anim-*-{n}.png" for n in SIZES))


if __name__ == "__main__":
    main()
