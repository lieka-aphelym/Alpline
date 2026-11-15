# Alpline (by lieka): FPV line of sight on Swiss terrain
*The code and the commands keep their short technical name `fpv3d` (e.g. `python -m fpv3d build ...`).*

Alpline builds a 3D map of any place in Switzerland from **swisstopo open data**. It then shows where your FPV radio link is likely to struggle:

- **Range spheres** are drawn around the pilot antenna, one per radio link (video, control…). Their size comes from a free-space link budget. A coloured ring marks where each sphere meets the ground.
- **Signal shadow ("dark zone")** is draped on the terrain. It marks every spot where a drone flying *N m above ground* has no direct line of sight to you, or where the Fresnel zone is obstructed. It is precomputed for several heights. In the viewer you can pick one, or let the overlay follow the drone's live height.
- **Flight log replay** (EdgeTX/OpenTX telemetry, Betaflight/INAV blackbox CSV, GPX): the track can be coloured by LOS status, predicted link margin, height, or any telemetry column (RSSI, LQ, SNR…). The HUD compares *predicted* and *logged* signal.

## Get it

- **Windows, no Python needed:** download `AlplineSetup.exe` from the
  [latest release](https://github.com/lieka-aphelym/Alpline/releases/latest) and run it. It installs for your user
  only (no administrator rights). The installer is not signed, so Windows SmartScreen may ask once: *More info* →
  *Run anyway*.
- **From the source** (Windows / macOS / Linux): see [Setup](#setup-windows--macos--linux-python--39) below.

What changed in each version: [CHANGELOG.md](CHANGELOG.md). Found a problem or have an idea? Open an
[issue](https://github.com/lieka-aphelym/Alpline/issues), with `logs/errors.txt` from your files folder if something
failed.

## How it is organised

Each place is just a YAML file in `data/locations/`. The easiest way to make one is the launcher's map page; an
example for the Gotthard Pass is in `examples/gotthard.yaml` (see [Use it](#use-it)). Nothing in the code is tied to a place.

Your own files (locations, flights, built scenes, packs, downloads) all live in `data/`, so the top of the project shows only the program. A project from before this layout moves them there by itself at the first start. Commands such as `python -m fpv3d build locations/gotthard.yaml` still work from the project folder: a path that is not found there is looked for in `data/`.

```
Alpline/
├─ fpv3d/            Python pipeline
│  ├─ geo.py         WGS84 ⇄ LV95 (swisstopo formulas), Grid
│  ├─ swisstopo.py   STAC API download + mosaic (swissALTI3D / swissSURFACE3D / SWISSIMAGE)
│  ├─ los.py         vectorised line-of-sight + Fresnel analysis
│  ├─ radio.py       link budget, free-space range, knife-edge diffraction
│  ├─ logs.py        flight-log readers (add new formats in READERS)
│  ├─ scene.py       builds scenes/<name>/ for the viewer
│  └─ cli.py         command line
├─ launcher/         the launcher window, one file per page (launcher.pyw starts it)
├─ viewer/           the pages: 3D viewer, map, packs, phone (three.js bundled in viewer/vendor, works offline)
├─ tests/            checks (run_all.py), a mock STAC server, demo-log generator
├─ examples/         an example location (gotthard.yaml)
└─ data/             your files, never in git:
   ├─ locations/     one YAML per flying spot (gotthard.yaml)
   ├─ logs/          your flight logs, blackbox downloads, live and training recordings
   ├─ scenes/        built 3D scenes (created by `build`)
   ├─ battery/       your packs and their history
   ├─ cache/         downloaded swisstopo tiles (reused between builds)
   └─ backups/, deleted/, launcher.json
```


## Start it: the launcher

Double-click **`Alpline.bat`** in the project folder (or start the installed app). The window has a rail of pages on
the left and a header that stays the same on every page:

- **Header:** *online / offline*, the server (*server full :8000*, or *off*), *[stop]*, *[3d viewer]* (opens the
  selected location) and *[locations map]*. Opening something starts the local server; closing the window stops it.
- **map:** a dark map of Switzerland and its neighbours (swisstopo's grey map), with relief shading inside Switzerland,
  everything outside the border dimmed, and the FOCA drone zones as red outlines (tick box to hide them). Drag to
  move, mouse wheel or *+ / −* to zoom, *fit* frames all your locations (it opens that way), *CH* shows the whole
  country. Zooming in loads sharper map tiles, down to towns, roads and rivers (about 13 m per pixel); the overview
  shows while they load. Locations are dots (yellow = built, grey ring = not built); nearby ones merge into a numbered
  group (click it to zoom in). Names appear next to the dots once you zoom in. Click = select, double-click = open;
  a click on an empty spot, *×* on the callout or **Esc** selects nothing (the plain map).
  The selected location's details sit in a callout next to its dot (size, terrain, build date, flights, *[open in 3d]*
  or *[build on the map]*, *[fly]*), with its real area drawn dashed. The **locations list** floats top left (filter
  box, real / sim logs, *[–]* folds it); the map's date and *[update map]* are bottom left. Everything you have seen is
  kept in `cache/launcher/` and shows offline; *[update map]* downloads the map again (latest zones) and the detailed
  tiles about 10 km around each location, so the map is sharp at the field without internet (new locations get theirs
  automatically when online).
- **drone:** finds a Betaflight drone and the radio on USB by itself (a dot on the rail icon). After a download it asks
  which battery pack you flew; *[battery packs]* opens the packs page (see [Battery analysis](docs/battery.md)). *[download blackbox]*
  copies the drone's log and adds its flights (see *Blackbox from the drone* below); *[live flight in 3d]* opens the
  selected location on the fly tab.
- **phone:** share on your network, the address and PIN, *[qr code]*, *[check access]* (details below).
- **checks:** when a library pinned in `requirements.txt` changed (after an update of Alpline), a notice lists what
  differs and *[update libraries]* installs it: no command line. *[run quick check]* runs Alpline's own tests (about 20 s, in a temporary folder: your locations are not
  touched), with a line per group (security, robustness, journeys…), what went wrong for a failure, and *[copy
  report]* to paste the results in a message. A red dot on the icon means the last check found a problem. From the
  source folder only (the installed app has no tests).
- **files:** how much space each kind of file takes, with free space on the disk (see *Your files: clean-up, start
  fresh, backup* below). **settings:** Full / Lite, where pages open (Alpline window or your browser), desktop
  shortcut, your files folder, version.

The window can be resized (the map grows, everything else keeps its size) and remembers its size and page. Long names
are cut with "…" (hover for the whole text). Messages appear for a few seconds at the top right. Keys: **Ctrl+F**
filter, **↑ ↓** move in the list, **Enter** open, **Esc** clear the filter. The locations reload when the window comes
back to the front.

**On your phone (Android or any phone with Chrome):** the **phone** page, then *[share on my network]*. The page shows the address (e.g. `http://192.168.1.20:8000`) and the PIN; **[qr code]** shows a QR code to scan. Phone and computer must be on the same Wi-Fi; at the field, turn on the phone's hotspot and connect the laptop to it. The first time, allow Python on *private networks* when Windows asks. On the phone the panel becomes a sheet at the bottom with the tabs along its top (*[hide]* folds it), buttons are bigger, and *Add to Home screen* in Chrome gives it an icon. The phone can look, fly the simulator, follow live telemetry (radio on the laptop) and build; deleting and renaming only work on the computer. The phone needs the 6-digit **PIN** once (it is in the QR link); without it other devices on the network get nothing. When the *cryptography* library is installed (the launcher offers it), the phone uses a secure page, `https://<PC address>:8443`: install the PC's certificate once on the phone (the QR page links it and explains the Android steps) so Chrome trusts it, which lets the phone keep its screen on during a live flight. The firewall rule made by the launcher covers ports 8000-8019 and 8443-8462. From a terminal: `python -m fpv3d serve --lan`.

Logs count as **sim** when they come from the training flight (`<location>_sim_<date>` or `logs/sim/`), everything else counts as **real**.

**Building safely:** the map page shows the size of a new location before you build it (scene size and memory needed) and asks before very large builds; a running build has **[cancel build]**. Only one build runs at a time, and the same location can never be built twice at once (another terminal or window is refused). Downloads from swisstopo are retried 3 times (after 5, 15 and 30 s) when the network hiccups. Library versions are fixed in `requirements.txt`.

**Disk space:** the launcher's **disk** page shows the size of the download cache, built locations, deleted locations and logs. *[clean unused tiles]* deletes downloaded tiles that none of your location files uses (1 km around each location is kept), *[empty deleted]* empties the deleted folder for good. From a terminal: `python -m fpv3d cache prune --dry-run`, then `python -m fpv3d cache prune`.

**Numbered locations:** a new location gets the next number in front of its name, with as many digits as your existing ones (e.g. `015_north_ridge` after `014_valley`, or `01_...` for the very first). Renaming keeps the number.

The viewer and the map page show the current mode in the small badge next to the title. From a terminal: `python -m fpv3d serve` (Full) or `python -m fpv3d serve --lite`, the same for `map` and `new`. `?mode=lite` / `?mode=full` in the viewer address overrides it for one page.

**What Lite changes** (everything else is the same program):

| | Full | Lite |
|---|---|---|
| overview mesh | 1500 × 1500 | 800 × 800 (`&maxgrid=` to change) |
| sharp close-up patch | 768 × 768 | 384 × 384 |
| pixels on high-DPI screens | up to 2× | up to 1.25× |
| new location: terrain (map page) | 2 m | 5 m |
| new location: aerial photo | 2 m | `auto`: sharpest that stays ≤ 2048 px |
| new location: signal grid | 10 m | 20 m |
| new location: flat shadow maps / antenna-edit steps | 4 / 11 | 2 / 4 |
| new location: 3D buildings, sharp near-pilot photo | on | off |

Both modes draw the 3D only when something changes (camera, playback, simulator, live data, a setting): the same
picture as drawing 60 times a second, with far less GPU work (`?render=always` draws continuously).

**Speed:** a build computes the 3D blind-spot volumes once and draws the flat shadow maps (10, 30, 60, 120 m) from
them, instead of computing each map separately: the signal step of a 5 × 5 km location at 2 m went from 24 s to 9 s
(same maps, checked by `test_snapshots.py`). The viewer gets the terrain in a compact form (0.1 m steps, half the
size), and the phone gets every scene file, page and flight log compressed (a 5 × 5 km location: about 13 MB down to
3–5 MB); this computer gets them uncompressed, where compressing would only cost time.

Existing location files keep their own values in both modes; edit them to change (e.g. `buildings: true`). On a 5 × 5 km test area a Lite location built in 2.3 s instead of 29 s, with 6–9× smaller terrain and shadow files.

**Panel and display** (both modes):

- **Plain panel in four tabs:** **[map]** (photo, camera, no-fly zones, this location), **[signal]** (where you lose the drone, radio range), **[flights]** (logs, comparison, video), **[fly]** (training flight, live flight with the radio + warnings). Each tab starts with a one-sentence answer (e.g. *Video reaches about 2.1 km. Flying at 30 m, the drone stays in sight over 64% of that area*); less used settings are under **+ Advanced**. The Switzerland map is the **[locations]** link at the top.
- **Radio setups instead of dB fields:** *[signal] → Radio range* offers ready-made choices per link (e.g. *25 mW · stock antennas (CH / EU limit)*, *500 mW · patch on the goggles*). The exact numbers are under *Advanced: exact radio values*.
- **Simpler signal display:** *clear*, *no line of sight* and *signal loss likely* (no separate Fresnel state).
- **Clean flight info box:** distance, height and speed in large type, one bar per radio link (margin, plus LQ when the log has it), the drone zone only when you're in one; the rest under *[more]*.
- **The pilot in the view:** close up a small tripod with a patch antenna at the real antenna height (written next to
  it) that turns toward the drone; further away a round radio badge on a thin mast. A ground disc with a north tick
  marks the spot, and dashed **distance rings** at 500 m, 1 km and 2 km lie on the terrain around it (*[map] → Advanced*
  turns them off). In a live flight that uses another pilot position (take-off point, phone GPS, picked on the map),
  the marker and the rings move there, and the location's own point stays as a faded grey ring with a dashed link and
  the distance between the two.
- **The drone in the view:** close up (under ~250 m from the camera) a small 3D quad that leans into turns and climbs, with a ring in the link colour; further away a round Alpline badge with a chevron pointing where it flies. Always a dashed line down to its shadow on the ground with the height above ground, and in replay a fading tail of the last 5 s. Same look in live flight (faded while the position is only estimated), the training flight's chase view (real attitude) and the see-through ghost of *Compare with*.
- **Dark / light theme:** the *[dark] [light]* switch next to the title, remembered per browser. Dark for indoors, light for sunlight at the field.
- **Playback bar:** small, and you can drag it anywhere by its grip (double-click the grip to put it back). In *[flights]*, the flight **(none)** hides the path, the drone, the info box and the bar.

## Alpline as an app

**Windows app.** The viewer and the locations map open in **Alpline windows**: Microsoft Edge (or Chrome) in app
mode, so no address bar or tabs and their own taskbar icon. Edge comes with Windows 10 / 11, nothing to install.
*[open in: window / browser]* in the launcher's status bar switches between that and your normal browser; the windows
close with the launcher. They use their own profile (`cache/appwindow/`), so the pages' settings (theme, warnings,
antenna edits) are separate from your browser's. If a window can't open, the page opens in the browser and
`logs/window.log` says why.

To make an installable program: double-click **`build_app.bat`** (a few minutes). It makes `dist\Alpline\Alpline.exe`
(Python and all libraries inside, about 200 MB) and, if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is
installed, the installer `dist\AlplineSetup.exe` (installs for your user only, Start menu + desktop icon, uninstall in
Windows settings). The first start asks where your files go: *Documents\Alpline*, or pick this project folder to keep
your locations, flights and downloaded maps. Inside: `Alpline.exe` (launcher and windows) and `alpline-cli.exe` (the
server and builds, runs hidden). Recipe: `packaging/alpline.spec`.

**Phone app.** With phone sharing on and the secure page set up (see *Phone*), Chrome on the phone offers
**Install app**: Alpline gets its own icon and opens full screen without the browser bar. It still needs Alpline
running on the computer; when it can't reach it, it says so instead of a browser error page.

## Setup (Windows / macOS / Linux, Python ≥ 3.9)

```bash
git clone https://github.com/lieka-aphelym/Alpline.git
cd Alpline
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python tests/run_all.py         # all checks (see docs/development.md)
```

## Use it

The commands below use the example location. Copy `examples/gotthard.yaml` to `data/locations/gotthard.yaml` first
(create the two folders if Alpline has not run yet), or make your own location on the launcher's map page.

```bash
# 1. Build the Gotthard Pass scene (downloads about 70 MB once, then cached)
python -m fpv3d build locations/gotthard.yaml

# 2. Add your flight logs (fast: reuses terrain)
python -m fpv3d add-log locations/gotthard.yaml logs/my_flight.csv

#    no log yet? generate a synthetic demo flight for the scene:
python tests/make_demo_log.py scenes/gotthard logs/demo_gotthard_edgetx.csv
python -m fpv3d add-log locations/gotthard.yaml logs/demo_gotthard_edgetx.csv

# 3. Open the 3D viewer in your browser
python -m fpv3d serve
```

**Motion vectors**: in the viewer's *Motion vectors* section you can toggle the velocity arrow (1st derivative of position, cyan) and the acceleration arrow (2nd derivative, violet). They are drawn on the drone, or along the whole track if you tick the option. Both are computed from the GPS positions with a central difference over a smoothing window (default 1 s). The track can also be coloured by speed or acceleration, and the HUD shows total, horizontal and vertical values.

**Flight video**: *[flights] → Load video (+ .srt)* plays your DVR (e.g. DJI O4 goggles recording plus its .srt) next to the 3D view. Use ⇄ to swap which one is full screen, and drag or resize the player. To sync, unlink, pause both on the same event, then press *Sync here* (add a 2nd point later in the flight to correct drift). The sync is remembered per flight. If the browser can't play H.265, run `python -m fpv3d video-convert DJI_xxxx.mp4` (needs ffmpeg).

Viewer controls: drag to rotate, right-drag to pan, scroll to zoom, click the terrain to read elevation and distance to the pilot, space to play/pause. If your GPU struggles, open `http://127.0.0.1:8000/viewer/?maxgrid=500`.

## Your files: clean-up, start fresh, backup

The launcher's **files** page lists what Alpline keeps, with the size of each: flight logs, training flights, built 3D
scenes, downloaded maps, locations, deleted items, app logs and launcher settings. Tick what to delete and click
*[delete selected]*; *[all: start fresh]* ticks everything (like a new install). Ticking locations also ticks their
scenes. **A backup zip is saved first** in the `backups` folder unless you untick *make a backup first*. Nothing else
in the folder is touched (when Alpline runs from its source folder, the program files sit next to your data), and
nothing is deleted while a location is building. *[clean unused tiles]* deletes only the downloaded tiles that none of
your locations uses.

*[make a backup…]* saves your locations, flights, training flights and settings in one zip (tick *include the built
3D scenes* to skip rebuilding after restoring). Use it to keep your files safe or to move to another PC.
**Once a week**, when the launcher starts, a small backup (no scenes, no maps) is saved by itself as
`backups/auto_<date>.zip`; the five newest are kept, and the files page shows the latest.
*[restore a backup…]* unpacks one. It asks whether to replace files you already have or only add what's missing, and
never deletes anything. Without the scenes, each location shows *not built*; build it and its flights come back.
A restore only writes Alpline's own kinds of files inside Alpline's folder: entries pointing anywhere else (`../`,
`C:\`, program files) or claiming an absurd size are refused, and files are copied in pieces.

**Problems are written down.** When something fails (a launcher button, a page, the server), you get a short notice
and the details go to `logs/errors.txt` (click the launcher's notice to open it). The pages report their errors there
too, including the phone, which has no developer tools. Send that file along when you report a problem (your home
folder is written as `~` in it, so your user name is not).
Settings, location files and scene files are saved through a temporary file, so a crash or power cut in the middle
never leaves a half-written file. A build stops right away with a clear message when the disk is too full for it.

## Supported logs

| source | how |
|---|---|
| EdgeTX / OpenTX | radio SD card `LOGS/*.csv` (enable logging with a Special Function). Reads `GPS`, `Alt`, `1RSS`, `RQly`, `RSNR`… |
| Betaflight blackbox, straight from the drone | flights tab → **[download from the drone]** (see below), or `python -m fpv3d blackbox [--file LOG.BBL]` |
| Betaflight / INAV blackbox | decode `.bbl` with `blackbox_decode` → `*.gps.csv`, or export CSV from Blackbox Explorer |
| GPX | any GPS app / converter |
| generic CSV | needs `lat`, `lon`, optional `alt` and `time` columns |

### Blackbox from the drone (USB)

Plug the drone in with its USB cable (no battery needed), close Betaflight Configurator, then **[download from the
drone]** in the flights tab (or `python -m fpv3d blackbox`). Alpline:

1. finds the flight controller among the serial ports (the one answering Betaflight's MSP protocol: the radio is left alone),
2. switches it to USB drive mode (Betaflight's `msc`; F4 / G4 / F7 / H7 boards with onboard flash or an SD card),
3. copies the logs to `logs/blackbox/<date>/`, reads the GPS of each flight (several flights in one file are split),
4. adds each flight to the location whose map contains its take-off point, named `<location>_bb_<date>_<time>`
   (tick *add every flight to this location* to force the open one). Flights outside every location are kept as CSV.

Downloading again skips flights already added (`logs/blackbox/added.txt`). The drone stays in drive mode until you unplug
it. GPS must be among the logged fields (Configurator → Blackbox). Erase the flash in the Configurator when you want.
Logs are read with [orangebox](https://github.com/atomgomba/orangebox) 0.4.0 (GPL-3; 0.5.0 does not install with pip).

## More

| Guide | What is in it |
| --- | --- |
| [Live flight](docs/live.md) | the drone live on the map from the radio's telemetry, the line-of-sight and battery warnings, the pilot position |
| [Battery analysis](docs/battery.md) | the battery tab, packs and their health, LiPo / Li-ion, notes, charger check |
| [Training flight](docs/training.md) | the simulator: radio setup, flight model, collisions, recording |
| [Locations, terrain and maps](docs/locations.md) | creating locations on the map, routes, terrain detail, buildings, no-fly zones, renaming, deleting |
| [Development](docs/development.md) | how the signal model works, the tests and tools |

## What's next

Ideas for future versions. These are intentions, not promises, and there are no dates.

**Planned**
- **Terrain outside Switzerland:** (high priority) a first step is in (not released yet): a location anywhere
  builds from the Copernicus 30 m model and the Sentinel-2 satellite photo, see
  [docs/locations.md](docs/locations.md#outside-switzerland); the map page and the launcher's map cover the world.
  Still to come: finer national elevation data and photos. Drone zones stay Switzerland-only at first; zones of
  other countries come later.
- **Better training flight:** today it feels floaty. More realistic physics, wind, and a more direct feel. (moderate priority)
- **A better-looking 3D world:** bridges, more detailed buildings, trees and other vegetation. (low priority, this could be a nice cosmetic change)

**Ideas**
- **Planes and VTOL:** fixed-wing and VTOL aircraft next to quads, in the training flight and in replay. (main focus remain on quadcopters)

Have a wish or want to help ? Open an [issue](https://github.com/lieka-aphelym/Alpline/issues).

## Data

Data: © swisstopo (swissALTI3D, swissSURFACE3D Raster, SWISSIMAGE 10 cm), free under the swisstopo open-data terms (OGD). It is fetched via the STAC API at `data.geo.admin.ch`. To test without internet: `python tests/mock_stac.py` and set `FPV3D_STAC_BASE=http://127.0.0.1:8765/api/stac/v0.9`. That serves synthetic terrain.

Always check the drone rules (FOCA / BAZL map at map.geo.admin.ch) before flying. Alpline is a planning aid: its
signal predictions and zone outlines can be wrong or out of date, and flying safely and legally stays your job.

## Licence

Alpline is free software under the [GNU General Public License, version 3](LICENSE): you may use, study, share and
change it, and versions you pass on must stay under the same licence. It comes with no warranty. The libraries and
data it uses are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
