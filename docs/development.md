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
- **GitHub:** `.github/workflows/checks.yml` runs `tools/check.py` and the Node tests on Windows and Linux at every
  push and pull request.
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
- **Warnings:** 33 situations with a fake hill, clock and sound: what the warning says (climb, turn, outside the map, weak signal) and what you hear in each mode (sentence once, climb sound repeating, "Climb" after three, muted groups silent, the lost tone). Needs [Node](https://nodejs.org); without it open `http://localhost:8000/viewer/test/` while Alpline runs. Run them after changing `viewer/js/drone/warn.js`.
- **Browser:** opens the checks page, the map, the share page, the packs page and your first location in Full and Lite, and lists page errors. Screenshots in `logs/checks/`. Failed downloads (no internet) are noted, not counted as errors.

Viewer code: `app.js` (scene, replay, panel), `hud.js` (info box), `links.js` (radio editor), `rename.js` (rename / delete), `warn.js` (warnings), `live.js`, `sim.js`, `detail.js`. `drone.js` draws the drone icon (live link indicator, training box, build card, share page, empty pages). Full / Lite / phone is decided once in `theme.js` and handed to the modules by `env.js`. The logo animation (spin-up when a page opens, spinning while something loads or builds) is in `theme.css`; the launcher plays frames made from it by `tools/render_logo_frames.py`. The logo itself (an edelweiss-propeller) is drawn by `tools/make_brand.py`, which writes every file in `viewer/brand/` and the `FLOWER` line of `theme.js`: change the geometry there, then run both tools.

## Where things are

```
fpv3d/            the Python side: building scenes, the server, logs, battery, radio maths
launcher.pyw      starts the launcher window (and is Alpline.exe in the installed app)
launcher/         the launcher, one file per page
  app.py            the window and what the pages share (header, rail, selecting a location, keys)
  map: mapview.py   drone.py   phone.py   checks.py   files.py   settings.py
  server.py         starting / stopping the local server, opening Alpline windows
  widgets.py        buttons, tooltips, pills, the logo animation;  style.py  colours, fonts, scaling
  common.py         paths, settings, small helpers;  main.py  start-up
viewer/           the pages (index = 3D viewer, map, packs, share, offline), sw.js, manifest
  css/              one stylesheet per page + theme.css (the look) + mobile.css
  js/core/          shared by every page: theme, tabs, text escaping, network, environment
  js/view/          the 3D viewer: app.js (scene, loading, playback), trackmath.js (speed, times),
                    colouring.js (path colours), terrain_shaders.js, camera, markers, links, video
  js/battery/ js/drone/ js/sim/ js/map/   one folder per topic
  brand/ vendor/    logo and icons; three.js and leaflet (works offline)
tests/  tools/  docs/  packaging/
data/             your files (never in git)
```

The launcher's pages are mixins: `class Launcher(ServerMixin, PhonePage, DronePage, ...)`. Each page file holds a
class with methods only; they all share the one launcher object (`self`), so a page can call any other part.
The HTML pages stay at the top of `viewer/` on purpose: their addresses are in phone bookmarks and the installed
phone app.

- **Server addresses:** each `POST` address is one method `_post_<name>` in `fpv3d/server.py`, listed in the `POST`
  table at the end of the handler class. `LOCAL_ONLY` lists the ones the phone may not call. Background jobs are
  registered with `new_job()` (one build at a time, the last 20 finished jobs kept).
- **Shared helpers:** `viewer/js/core/net.js` (`postJSON`, `getJSON`), `viewer/js/core/screen.js` (`pxPerUnit`: sizes that stay fixed
  on screen), `viewer/js/core/esc.js` (text safe for HTML); `fpv3d/filelock.py` (a lock between programs),
  `fpv3d/safefile.py` (writes that never leave half a file), `fpv3d/errorlog.py`.
- **Types:** `mypy` checks eleven modules (see `pyproject.toml`); add a module there when it is clean.

## Making a release

1. Set the version in `fpv3d/__init__.py` (the launcher's settings page and the installer read it from there) and
   add a section to `CHANGELOG.md`.
2. `python tests/run_all.py --browser`, then commit and push; wait for the GitHub checks to turn green.
3. Double-click `build_app.bat` (needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer). Install
   `dist\AlplineSetup.exe` on a PC, start it once and build a location.
4. Tag and publish, with the installer attached:
   `git tag v1.0.0`, `git push origin v1.0.0`, then
   `gh release create v1.0.0 dist/AlplineSetup.exe --title "Alpline 1.0.0" --notes-file CHANGELOG.md`
   (or *Releases → Draft a new release* on github.com). The README's download link points at the latest release.

The installed app contains orangebox (GPL-3), so every installer you publish must come with the matching source:
the tag does that. `THIRD_PARTY.md` lists the libraries; update it when `requirements.txt` gains one.

## Renaming the app

The name is defined once, in `fpv3d/brand.py` (`APP_NAME`, and `BY` for the maker's name). The launcher, its texts,
the taskbar id, the desktop shortcut, the server's messages and the pages all read it; the pages get it from the
server and `viewer/js/core/theme.js` puts it into every text and title. After changing it:

- your existing files are still found: the folders of `EARLIER_NAMES` are used when the new one does not exist
- internal names stay (`ALPLINE_DATA`, `alpline-cli.exe`, backup file names, the firewall rule, the package `fpv3d`)
- the installer (`packaging/alpline.iss`), `Alpline.bat`, `build_app.bat` and this documentation spell the name
  themselves: change them by hand
- the logo images in `viewer/brand/` are pictures made by `tools/make_brand.py`: run it again if the logo changes

## No personal data in the project

Scene files store each log's place relative to your Alpline folder (`logs/sim/x.csv`), never the full path, which
would hold your Windows user name; older scene files are rewritten when the launcher starts. `logs/errors.txt` writes
your home folder as `~`. Your locations, flights, scenes, settings and backups are not part of the git repository
(`.gitignore`).

## The look, in one place

The pages follow one style ("flight OSD"); the rules are at the end of `viewer/css/theme.css`.

- Text sizes: 10 (small capitals), 11 (notes), 12 (buttons and figures), 13 (sentences), 15 (titles), 19 (big numbers). No half pixels.
- Square corners everywhere; only round things (dots, dials) are round.
- Buttons read `[lowercase]`. `.primary` is filled with the accent colour (the one thing to do next), `.danger` is outlined in red (it deletes).
- Colours come from the variables at the top of `theme.css` (`--t-bg`, `--t-fg`, `--t-acc`, `--ok`, `--warn`, `--bad`, `--c-cur` for current). Do not write a colour code in a page; map markers and chart lines are the exception.
- The launcher follows the same rules in Tkinter: every button comes from `Launcher.button()` (class `Btn`: normal, `primary=True`, `danger=True`; a switched-off button turns grey by itself), text sizes are `MONO_S` (9), `MONO` / `MONO_B` (10) and `SANS` for sentences, status colours are `OK`, `WARN`, `BAD`.
