# Development: how it works, checks

[← back to the README](../README.md)

## How the signal model works (and its limits)

1. **Range sphere.** Radius = distance where `Ptx + Gtx + Grx − losses − FSPL(d) = sensitivity + fade margin`.
2. **Line of sight.** For every map cell, a ray goes from your antenna to a drone hovering *N m* above that cell. The ray is sampled against the terrain, including earth curvature with a k = 4/3 refraction factor. The pipeline records the smallest clearance, and that clearance divided by the first-Fresnel-zone radius. Less than 60 % Fresnel clearance is shown amber. Blocked is shown dark.
3. **Predicted margin.** This is FSPL plus a single knife-edge diffraction loss (ITU-R P.526). Black areas or red track samples mean the model expects the link to drop.

It's a planning aid. Multipath, your body and goggles, antenna patterns and polarisation, interference and foliage all matter in reality. `dtm` ignores trees completely. Compare the predicted margin with the logged RSSI/LQ, then tune `fade_margin_db` until the two match for your gear.

## Checks

```bash
python tests/run_all.py             # everything below (except the browser)
python tests/run_all.py --browser   # + opens the pages in a hidden browser (needs: pip install playwright; python -m playwright install chromium)
python tools/check.py               # the quick check: ruff + all Python tests (~10 s)
python tests/run_quick.py           # the launcher's [run quick check]: one line per test
```

For development: `pip install -r requirements-dev.txt` (pytest, ruff, coverage, mypy), then `python -m pytest`
(add `--cov` to see which code the tests reach), `ruff check .` (style and likely bugs) and `mypy` (types of the core
modules). `python tools/install_hooks.py` runs `tools/check.py` before every `git commit`; `git commit --no-verify`
skips it once. Settings for all of these are in `pyproject.toml`.

- **Basics** (`test_basic.py`): coordinates, log readers, radio maths, the telemetry parser, blackbox reading, map tiles.
- **Server** (`test_server.py`): the pages load, bad requests are refused, one build per location, cache cleaning keeps used tiles, the https certificate.
- **Security** (`test_security.py`): other web pages open in your browser can't use Alpline (requests must be JSON from
  Alpline's own address; a website's own name pointing at 127.0.0.1 is refused), only the pages and scenes are served
  (never locations, logs, settings or code), names with `..` or `/` are refused, the phone needs the PIN everywhere
  (10 wrong tries: one minute locked) and can't delete or rename. Names from files and the internet (OpenStreetMap
  buildings, zones, locations, flights, serial ports) are shown as text, never run as code; a security policy lets
  only Alpline's own scripts run and forbids other sites from showing Alpline in a frame; requests are limited to 20 MB.
- **Battery** (`test_battery.py`): the analysis finds the resistance a simulated pack was given (2, 4.5 and 9 mΩ per
  cell), mAh within 2 %, glitches like the real ones (32 V, 184 A) don't change the result, cells by Betaflight's rule,
  radio-log columns, logs without a current sensor or too short; a blackbox with a GPS flight and a battery-only one
  (both kept, the GPS one linked to its 3D track and path colours, kept by a rebuild, not added twice); packs, flags,
  landing advice, the charger check's Betaflight scale, notes (a crash checked against the resistance before / after,
  a swollen pack to retire); the battery API (the phone can't delete packs or notes).
- **Coverage:** `python tools/cover.py` measures the tests and the commands they start as separate programs
  (plain `pytest --cov` misses those): 69 % overall in November 2026. `htmlcov/index.html` shows it line by line.
- **GitHub:** `docs/github-checks.yml` is a ready workflow: copied to `.github/workflows/checks.yml`, it runs
  `tools/check.py` and the Node tests on Windows and Linux at every push. To put the project on GitHub (private):
  create an empty private repository on github.com, then in the project folder
  `git remote add origin https://github.com/<you>/<name>.git` and `git push -u origin main`.
- **Your files** (`test_files.py`): safe saving keeps the old file when writing fails, the error log stays small,
  clean-up deletes only the ticked kinds (never the program), backup → start fresh → restore gives everything back,
  unsafe zip entries are refused, nothing is deleted while building, a build stops when the disk is too full.
- **Robustness** (`test_robust.py`): hundreds of damaged inputs (cut, flipped bytes, junk) for the radio telemetry,
  flight logs, blackbox files and location files: a clear error or a result, never a crash or a hang.
- **Journeys** (`test_journeys.py`): the real commands in a fresh data folder against the fake swisstopo service:
  build, add a log, rename the log and the location, delete, restore, empty the bin; rename never overwrites;
  blackbox twice adds once; cache cleaning keeps what locations need; one broken location file doesn't stop the others.
- **Snapshots** (`test_snapshots.py`): line of sight, blind-spot heights and radio range on a fixed test terrain,
  compared with `tests/snapshots/signal.json`. When a change is meant to move them: `UPDATE_SNAPSHOTS=1 python -m pytest tests/test_snapshots.py`.
- **Launcher** (`test_launcher.py`): USB detection (drone, radio, busy, unplugged during a download), map groups and
  zoom levels, and the real window at its smallest size: panels inside and apart, long texts never resize it.
- **Warnings:** 33 situations with a fake hill, clock and sound: what the warning says (climb, turn, outside the map, weak signal) and what you hear in each mode (sentence once, climb sound repeating, "Climb" after three, muted groups silent, the lost tone). Needs [Node](https://nodejs.org); without it open `http://localhost:8000/viewer/test/` while Alpline runs. Run them after changing `viewer/warn.js`.
- **Browser:** opens the checks page, the map, the share page, the packs page and your first location in Full and Lite, and lists page errors. Screenshots in `logs/checks/`. Failed downloads (no internet) are noted, not counted as errors.

Viewer code: `app.js` (scene, replay, panel), `hud.js` (info box), `links.js` (radio editor), `rename.js` (rename / delete), `warn.js` (warnings), `live.js`, `sim.js`, `detail.js`. `drone.js` draws the drone icon (live link indicator, training box, build card, share page, empty pages). Full / Lite / phone is decided once in `theme.js` and handed to the modules by `env.js`. The logo animation (spin-up when a page opens, spinning while something loads or builds) is in `theme.css`; the launcher plays frames made from it by `tools/render_logo_frames.py` (run it again after changing the logo).

## Where things are

- **Server addresses:** each `POST` address is one method `_post_<name>` in `fpv3d/server.py`, listed in the `POST`
  table at the end of the handler class. `LOCAL_ONLY` lists the ones the phone may not call. Background jobs are
  registered with `new_job()` (one build at a time, the last 20 finished jobs kept).
- **Shared helpers:** `viewer/net.js` (`postJSON`, `getJSON`), `viewer/screen.js` (`pxPerUnit`: sizes that stay fixed
  on screen), `viewer/esc.js` (text safe for HTML); `fpv3d/filelock.py` (a lock between programs),
  `fpv3d/safefile.py` (writes that never leave half a file), `fpv3d/errorlog.py`.
- **Types:** `mypy` checks eleven modules (see `pyproject.toml`); add a module there when it is clean.
