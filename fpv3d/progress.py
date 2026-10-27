"""Machine-readable progress events for the map page's live build animation.

When FPV3D_PROGRESS=1 (set by the local server for background builds), events are written to
stderr as single lines starting with '@@' followed by JSON. The server parses them; in a normal
terminal nothing extra is printed.

Events:
  phase  {id: terrain|ortho|los|tracks|zones|done, label}
  tiles  {kind, res, keys: ["E-N", ...], cached: ["E-N", ...]}      tiles needed by this step
  query  {kind, res, n}                                              asking swisstopo which files exist
  tile   {kind, res, key, state: download|done|raw|empty, pct?, bytes?, total?}
  pct    {phase, pct, label?}                                        progress inside a computation
"""
from __future__ import annotations

import json
import os
import sys
import time

ENABLED = os.environ.get("FPV3D_PROGRESS") == "1"
_last = {}


def emit(ev: str, throttle: float = 0.0, **kw):
    if not ENABLED:
        return
    if throttle:
        k = (ev, kw.get("key"), kw.get("phase"))
        now = time.monotonic()
        if now - _last.get(k, 0) < throttle:
            return
        _last[k] = now
    sys.stderr.write("\n@@" + json.dumps(dict(ev=ev, **kw), separators=(",", ":")) + "\n")
    sys.stderr.flush()
