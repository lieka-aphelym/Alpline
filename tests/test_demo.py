"""The online demo (tools/build_demo.py): a copy of the viewer that runs from plain static files."""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def test_demo_is_put_together_from_a_built_scene():
    """The demo holds the viewer, the chosen scene and its index; the copy no longer asks the server for its mode,
    hides what needs the app, says it is a demo and sends "Locations" to the download page. The source viewer is
    left as it was (if viewer/index.html changes so that a patch no longer applies, the script stops and says so:
    this test then fails before the demo does)."""
    import build_demo
    src_page = (ROOT / "viewer" / "index.html").read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="alpline_demo_"))
    scene = tmp / "scenes" / "spot"
    scene.mkdir(parents=True)
    (scene / "scene.json").write_text(json.dumps({"title": "A spot", "tracks": [{"file": "tracks/a.json"}]}), encoding="utf-8")
    (scene / "terrain.f32").write_bytes(b"\0" * 16)
    out = tmp / "_site"
    build_demo.main(["--scenes", str(tmp / "scenes"), "--pick", "spot", "--out", str(out)])
    page = (out / "demo" / "viewer" / "index.html").read_text(encoding="utf-8")
    assert "/api/mode.js" not in page and '<script src="demo.js"></script>' in page and "demo.css" in page
    assert "demoBadge" in page and build_demo.RELEASES in page and 'href="map.html"' not in page
    assert "ALPLINE_DEMO" in (out / "demo" / "viewer" / "demo.js").read_text(encoding="utf-8")
    assert "#liveSection" in (out / "demo" / "viewer" / "demo.css").read_text(encoding="utf-8")
    assert (out / "demo" / "viewer" / "js" / "view" / "app.js").exists()
    assert (out / "demo" / "scenes" / "spot" / "terrain.f32").exists()
    assert json.loads((out / "demo" / "scenes" / "index.json").read_text(encoding="utf-8")) == [
        {"name": "spot", "title": "A spot", "tracks": 1}]
    assert "demo/viewer/index.html?scene=spot" in (out / "index.html").read_text(encoding="utf-8")
    assert (out / ".nojekyll").exists()
    assert (ROOT / "viewer" / "index.html").read_text(encoding="utf-8") == src_page      # the source is untouched


if __name__ == "__main__":
    test_demo_is_put_together_from_a_built_scene()
    print("ok")
