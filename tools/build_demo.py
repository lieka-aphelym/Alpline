"""Put together the online demo: the 3D viewer as plain static files plus a few ready-built scenes, for a web host
with no Alpline server behind it (GitHub Pages).

    python tools/build_demo.py --scenes <data>/scenes --pick rochers_de_naye --out _site

Writes <out>/index.html (sends the visitor to the first scene), <out>/demo/viewer/ (a copy of viewer/) and
<out>/demo/scenes/<name>/ with an index.json listing them. The viewer already works without the server (it reads the
whole terrain file instead of asking for a lighter one); this script only changes the copy:
  - /api/mode.js (written by the server) becomes demo.js, which says "full mode, demo";
  - demo.css hides what needs the Alpline app on a computer: live flight with the radio, downloading from the drone,
    battery history, renaming and deleting;
  - the "Locations" link (the map page needs the server) leads to the download page instead.
The source viewer/ is never changed.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES = "https://github.com/lieka-aphelym/Alpline/releases/latest"

DEMO_JS = """// The online demo has no Alpline server: this stands in for /api/mode.js.
window.FPV3D_MODE = 'full';
window.ALPLINE_DEMO = true;
"""

DEMO_CSS = """/* Online demo: hide what needs the Alpline app and its server on a computer. */
#liveSection, #bbGet, label:has(#bbHere), #bbLog, button[data-tab="battery"], #batSection,
#locRenBtn, #trkRenBtn, #zonesRefresh, section:has(#locDelOk) .row:has(#locRenBtn) { display: none !important; }
.demoBadge { position: fixed; left: 50%; transform: translateX(-50%); bottom: 58px; z-index: 40;
  display: flex; align-items: center; gap: 12px; padding: 8px 10px 8px 14px; font: 13px system-ui, sans-serif;
  background: var(--t-bg, #0b0d10); color: var(--t-fg, #e8ecf1); border: 1px solid var(--t-rule2, #4a5462); }
.demoBadge a { color: #0b0d10 !important; background: #ffd60a; padding: 6px 12px;
  font-weight: 600; text-decoration: none; }
.demoBadge button { background: none; border: 0; color: inherit; font-size: 16px; cursor: pointer; padding: 2px 6px; }
@media (max-width: 600px) { .demoBadge { bottom: 70px; width: max-content; max-width: calc(100% - 24px); } }
"""

BADGE = (f'<div class="demoBadge" role="note">Online demo: a ready-built place. Build your own with the app.'
         f'<a href="{RELEASES}">Download for Windows</a>'
         '<button type="button" aria-label="Close" onclick="this.parentNode.remove()">×</button></div>')


def patch_viewer(viewer: Path) -> None:
    page = viewer / "index.html"
    s = page.read_text(encoding="utf-8")
    swaps = [
        ('<script src="/api/mode.js"></script>', '<script src="demo.js"></script>'),
        ('<a class="navlink" href="map.html" title="The map: all your locations, create new ones">Locations</a>',
         f'<a class="navlink" href="{RELEASES}" title="Alpline for Windows: build your own places">Get Alpline</a>'),
        ("</head>", '<link rel="stylesheet" href="demo.css">\n</head>'),
        ("</body>", BADGE + "\n</body>"),
    ]
    for old, new in swaps:
        if s.count(old) != 1:
            raise SystemExit(f"viewer/index.html changed: cannot find {old[:60]!r} exactly once; update tools/build_demo.py")
        s = s.replace(old, new)
    page.write_text(s, encoding="utf-8", newline="\n")
    (viewer / "demo.js").write_text(DEMO_JS, encoding="utf-8", newline="\n")
    (viewer / "demo.css").write_text(DEMO_CSS, encoding="utf-8", newline="\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scenes", required=True, type=Path, help="the scenes folder of a data folder")
    ap.add_argument("--pick", nargs="+", required=True, help="scene names to include, the first one opens")
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    a = ap.parse_args(argv)
    out = a.out
    if out.exists():
        shutil.rmtree(out)
    demo = out / "demo"
    shutil.copytree(ROOT / "viewer", demo / "viewer", ignore=shutil.ignore_patterns("concepts", "test", "*.map"))
    patch_viewer(demo / "viewer")
    listing = []
    for name in a.pick:
        src = a.scenes / name
        if not (src / "scene.json").exists():
            raise SystemExit(f"no built scene {src}")
        shutil.copytree(src, demo / "scenes" / name)
        m = json.loads((src / "scene.json").read_text(encoding="utf-8"))
        listing.append(dict(name=name, title=m.get("title", name), tracks=len(m.get("tracks", []))))
    (demo / "scenes" / "index.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    first = a.pick[0]
    (out / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>Alpline demo</title>'
        f'<meta http-equiv="refresh" content="0; url=demo/viewer/index.html?scene={first}">'
        f'<a href="demo/viewer/index.html?scene={first}">Open the Alpline demo</a>\n', encoding="utf-8")
    (out / ".nojekyll").touch()                 # GitHub Pages: serve the files as they are
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"demo written to {out} ({size / 1e6:.1f} MB): {', '.join(a.pick)}")


if __name__ == "__main__":
    main()
