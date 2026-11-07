# Alpline (by lieka): FPV line of sight on Swiss terrain
*The code and the commands keep their short technical name `fpv3d` (e.g. `python -m fpv3d build ...`).*

Alpline builds a 3D map of any place in Switzerland from **swisstopo open data**. It then shows where your FPV radio link is likely to struggle:

- **Range spheres** are drawn around the pilot antenna, one per radio link (video, control…). Their size comes from a free-space link budget. A coloured ring marks where each sphere meets the ground.
- **Signal shadow ("dark zone")** is draped on the terrain. It marks every spot where a drone flying *N m above ground* has no direct line of sight to you, or where the Fresnel zone is obstructed. It is precomputed for several heights. In the viewer you can pick one, or let the overlay follow the drone's live height.
- **Flight log replay** (EdgeTX/OpenTX telemetry, Betaflight/INAV blackbox CSV, GPX): the track can be coloured by LOS status, predicted link margin, height, or any telemetry column (RSSI, LQ, SNR…). The HUD compares *predicted* and *logged* signal.

Moléson is set up as the first location. Nothing in the code is tied to it. Each place is just a YAML file in `locations/`.

```
fpv3d/
├─ fpv3d/            Python pipeline
│  ├─ geo.py         WGS84 ⇄ LV95 (swisstopo formulas), Grid
│  ├─ swisstopo.py   STAC API download + mosaic (swissALTI3D / swissSURFACE3D / SWISSIMAGE)
│  ├─ los.py         vectorised line-of-sight + Fresnel analysis
│  ├─ radio.py       link budget, free-space range, knife-edge diffraction
│  ├─ logs.py        flight-log readers (add new formats in READERS)
│  ├─ scene.py       builds scenes/<name>/ for the viewer
│  └─ cli.py         command line
├─ viewer/           Three.js viewer (three.js bundled in viewer/vendor, works offline)
├─ locations/        one YAML per flying spot (moleson.yaml)
├─ logs/             put your flight logs here
├─ scenes/           generated output (created by `build`)
├─ cache/            downloaded swisstopo tiles (reused between builds)
└─ tests/            checks (run_all.py), a mock STAC server, demo-log generator
```


## Start it: the launcher

Double-click **`Alpline.bat`** in the project folder (or start the installed app). The window has a rail of pages on
the left and a header that stays the same on every page:

- **Header:** *online / offline*, the server (*server full :8000*, or *off*), *[stop]*, *[3d viewer]* (opens the
  selected location) and *[locations map]*. Opening something starts the local server; closing the window stops it.
- **map:** a dark map of Switzerland with relief shading and the FOCA drone zones as red outlines (tick box to hide
  them). Drag to move, mouse wheel or *+ / −* to zoom, *fit* frames all your locations (it opens that way), *CH* shows
  the whole country. Locations are dots (yellow = built, grey ring = not built); nearby ones merge into a numbered
  group (click it to zoom in). Names appear next to the dots once you zoom in. Click = select, double-click = open;
  a click on an empty spot, *×* on the callout or **Esc** selects nothing (the plain map).
  The selected location's details sit in a callout next to its dot (size, terrain, build date, flights, *[open in 3d]*
  or *[build on the map]*, *[fly]*), with its real area drawn dashed. The **locations list** floats top left (filter
  box, real / sim logs, *[–]* folds it); the map's date and *[update map]* are bottom left. The map, relief and zones
  are downloaded once into `cache/launcher/` so they show offline.
- **drone:** finds a Betaflight drone and the radio on USB by itself (a dot on the rail icon). *[download blackbox]*
  copies the drone's log and adds its flights (see *Blackbox from the drone* below); *[live flight in 3d]* opens the
  selected location on the fly tab.
- **phone:** share on your network, the address and PIN, *[qr code]*, *[check access]* (details below).
- **disk:** space used and clean-up. **settings:** Full / Lite, where pages open (Alpline window or your browser),
  desktop shortcut, your files folder, version.

The window can be resized (the map grows, everything else keeps its size) and remembers its size and page. Long names
are cut with "…" (hover for the whole text). Messages appear for a few seconds at the top right. Keys: **Ctrl+F**
filter, **↑ ↓** move in the list, **Enter** open, **Esc** clear the filter. The locations reload when the window comes
back to the front.

**On your phone (Android or any phone with Chrome):** the **phone** page, then *[share on my network]*. The page shows the address (e.g. `http://192.168.1.20:8000`) and the PIN; **[qr code]** shows a QR code to scan. Phone and computer must be on the same Wi-Fi; at the field, turn on the phone's hotspot and connect the laptop to it. The first time, allow Python on *private networks* when Windows asks. On the phone the panel becomes a sheet at the bottom with the tabs along its top (*[hide]* folds it), buttons are bigger, and *Add to Home screen* in Chrome gives it an icon. The phone can look, fly the simulator, follow live telemetry (radio on the laptop) and build; deleting and renaming only work on the computer. The phone needs the 6-digit **PIN** once (it is in the QR link); without it other devices on the network get nothing. When the *cryptography* library is installed (the launcher offers it), the phone uses a secure page, `https://<PC address>:8443`: install the PC's certificate once on the phone (the QR page links it and explains the Android steps) so Chrome trusts it, which lets the phone keep its screen on during a live flight. The firewall rule made by the launcher covers ports 8000-8019 and 8443-8462. From a terminal: `python -m fpv3d serve --lan`.

Logs count as **sim** when they come from the training flight (`<location>_sim_<date>` or `logs/sim/`), everything else counts as **real**.

**Building safely:** the map page shows the size of a new location before you build it (scene size and memory needed) and asks before very large builds; a running build has **[cancel build]**. Only one build runs at a time, and the same location can never be built twice at once (another terminal or window is refused). Downloads from swisstopo are retried 3 times (after 5, 15 and 30 s) when the network hiccups. Library versions are fixed in `requirements.txt`.

**Disk space:** the launcher's **disk** page shows the size of the download cache, built locations, deleted locations and logs. *[clean unused tiles]* deletes downloaded tiles that none of your location files uses (1 km around each location is kept), *[empty deleted]* empties the deleted folder for good. From a terminal: `python -m fpv3d cache prune --dry-run`, then `python -m fpv3d cache prune`.

**Numbered locations:** a new location gets the next number in front of its name, with as many digits as your existing ones (e.g. `015_gruyere` after `014_vanil_noir`, or `01_...` for the very first). Renaming keeps the number.

The viewer and the map page show the current mode in the small badge next to the title. From a terminal: `python -m fpv3d serve` (Full) or `python -m fpv3d serve --lite`, the same for `map` and `new`. `?mode=lite` / `?mode=full` in the viewer address overrides it for one page.

**What Lite changes** (everything else is the same program):

| | Full | Lite |
|---|---|---|
| 3D drawing | continuously | only when something changes (camera, playback, simulator, live data, a setting) |
| overview mesh | 1500 × 1500 | 800 × 800 (`&maxgrid=` to change) |
| sharp close-up patch | 768 × 768 | 384 × 384 |
| pixels on high-DPI screens | up to 2× | up to 1.25× |
| new location: terrain (map page) | 2 m | 5 m |
| new location: aerial photo | 2 m | `auto`: sharpest that stays ≤ 2048 px |
| new location: signal grid | 10 m | 20 m |
| new location: flat shadow maps / antenna-edit steps | 4 / 11 | 2 / 4 |
| new location: 3D buildings, sharp near-pilot photo | on | off |

Existing location files keep their own values in both modes; edit them to change (e.g. `buildings: true`). On a 5 × 5 km test area a Lite location built in 2.3 s instead of 29 s, with 6–9× smaller terrain and shadow files.

**Panel and display** (both modes):

- **Plain panel in four tabs:** **[map]** (photo, camera, no-fly zones, this location), **[signal]** (where you lose the drone, radio range), **[flights]** (logs, comparison, video), **[fly]** (training flight, live flight with the radio + warnings). Each tab starts with a one-sentence answer (e.g. *Video reaches about 2.1 km. Flying at 30 m, the drone stays in sight over 64% of that area*); less used settings are under **+ Advanced**. The Switzerland map is the **[locations]** link at the top.
- **Radio setups instead of dB fields:** *[signal] → Radio range* offers ready-made choices per link (e.g. *25 mW · stock antennas (CH / EU limit)*, *500 mW · patch on the goggles*). The exact numbers are under *Advanced: exact radio values*.
- **Simpler signal display:** *clear*, *no line of sight* and *signal loss likely* (no separate Fresnel state).
- **Clean flight info box:** distance, height and speed in large type, one bar per radio link (margin, plus LQ when the log has it), the drone zone only when you're in one; the rest under *[more]*.
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
cd fpv3d
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python tests/run_all.py         # all checks (see Checks below)
```

## Use it

```bash
# 1. Build the Moléson scene (downloads ~40 MB of tiles once, then cached)
python -m fpv3d build locations/moleson.yaml

# 2. Add your flight logs (fast: reuses terrain)
python -m fpv3d add-log locations/moleson.yaml logs/my_flight.csv

#    no log yet? generate a synthetic demo flight for the scene:
python tests/make_demo_log.py scenes/moleson logs/demo_moleson_edgetx.csv
python -m fpv3d add-log locations/moleson.yaml logs/demo_moleson_edgetx.csv

# 3. Open the 3D viewer in your browser
python -m fpv3d serve
```

**Motion vectors**: in the viewer's *Motion vectors* section you can toggle the velocity arrow (1st derivative of position, cyan) and the acceleration arrow (2nd derivative, violet). They are drawn on the drone, or along the whole track if you tick the option. Both are computed from the GPS positions with a central difference over a smoothing window (default 1 s). The track can also be coloured by speed or acceleration, and the HUD shows total, horizontal and vertical values.

**Flight video**: *[flights] → Load video (+ .srt)* plays your DVR (e.g. DJI O4 goggles recording plus its .srt) next to the 3D view. Use ⇄ to swap which one is full screen, and drag or resize the player. To sync, unlink, pause both on the same event, then press *Sync here* (add a 2nd point later in the flight to correct drift). The sync is remembered per flight. If the browser can't play H.265, run `python -m fpv3d video-convert DJI_xxxx.mp4` (needs ffmpeg).

Viewer controls: drag to rotate, right-drag to pan, scroll to zoom, click the terrain to read elevation and distance to the pilot, space to play/pause. If your GPU struggles, open `http://127.0.0.1:8000/viewer/?maxgrid=500`.

## Live telemetry from the radio + warnings for the pilot

The *Live flight* section of the *[fly]* tab shows the drone live on the 3D map from your radio's telemetry (ELRS / CRSF), warns the pilot before he flies into a zone without line of sight, and marks the last known position plus a likely impact zone if the link is lost.

**Setup (EdgeTX, e.g. RadioMaster TX15)**
1. Install the serial library once: `pip install pyserial`.
2. On the radio, set *SYS → Hardware → USB-VCP* to **Telemetry mirror** (EdgeTX 2.9+; the menu name can differ slightly between versions).
3. Plug the radio in USB and choose **USB Serial (VCP)** when it asks.
4. In the viewer, open *[fly]*, click *[refresh]*, pick the port and click *[connect]*. Connect while the drone is still on the ground: its GPS altitude is then calibrated against the terrain. You can also type an altitude correction yourself.

**What you get**
- **Live drone:** the drone moves on the map with a trail coloured by LQ, a dashed line shows where it will be in a few seconds, and you see LQ, RSSI, SNR, TX power, battery, flight mode, height above ground, speed, distance and satellites.
- **Warnings (voice + beeps, through the laptop speaker or an earbud):** the path of the next seconds (*Look ahead*, 5 s by default) is checked against the 3D shadows of the scene, i.e. the height below which there is no line of sight to the pilot:
  - "Blind zone ahead, climb 30" (or "..., turn left" when climbing is not enough), with slow beeps
  - "Blind zone close, climb 30 now" / "..., turn back now", with fast beeps
  - "No line of sight, climb 40" (or "..., turn right"), with double beeps
  - "Signal weak" when the real LQ drops, "Signal weak, turn back" when it is very low
  - "Clear", once it's safe again

  The voice always says the reason first, then one action. When the warning goes on, it only repeats the action ("Climb 35", "Turn left now"). Directions are from the drone's direction of flight: *bear left/right* (a small turn), *turn left/right*, *turn back*. A coloured box at the top of the screen shows the same thing for a spotter (title, action, seconds and metres), with a small clock dial for the escape direction.

  **Command sounds.** Under *[fly] → Warnings → Alerts* you choose *Sounds + voice the first time* (default: the sentence once when something new happens, then only the sound repeats), *Sounds only*, *Voice + beeps* (the sentences and plain beeps) or *Off*. Each command has its own sound, and it repeats faster when it gets closer (every 1.6 s ahead, 0.7 s close):
  - climb: a rising sweep (twice = climb more than 40 m). It repeats faster than the other sounds (every 0.9 s, 0.6 s when close) for as long as you still have to climb; with no line of sight the buzz only comes every 3rd time. In *Sounds + voice the first time* mode, the voice says "Climb" after every three sweeps
  - left / right: a double tick in that ear only (use stereo earbuds)
  - turn back: two falling tones, left then right
  - no line of sight: a low harsh double buzz, followed by the action
  - signal weak: a soft low wobble (followed by "turn back" when very weak)
  - signal lost: one long low tone
  - clear: two bright rising notes

  The buttons under *Alerts* play each sound, to learn them before flying (the simulator warns too). Untick a sound to switch it off: that warning then stays silent, voice included, and only shows on screen. If a warning combines two sounds (no line of sight + climb), the other one still plays.
- **No-fly zone age:** *[map] → No-fly zones* shows the date of the zone data, says *refresh before flying* when it is more than a week old, and **[refresh zones]** downloads the current FOCA zones for this location.
- **Safety checks during a live flight:**
  - The warning sounds run on their own timer. If the Alpline page goes to the background, the voice says *"Alpline is in the background. Warnings may be late"*, and the panel reminds you afterwards: browsers slow down hidden pages, so keep Alpline in front. On the PC the screen is kept on while connected.
  - If the drone leaves the built area there is no shadow data under it: you get **OUTSIDE THE MAP** (turn-back sound) instead of a silent "all clear".
  - When the drone sits on the ground at connect, its position is compared with the location's pilot point. More than 75 m apart: a note in the panel and a spoken warning, and **[use the takeoff point as pilot]** moves the pilot point there and rebuilds the shadows.
  - At connect, the panel lists what is switched off (sounds, voice, warning box), so a flight never starts silent without you knowing.
- **Signal lost:** after 1.5 s without GPS telemetry there is one long tone and "Signal lost". A red pin marks the last fix and a red area the likely impact zone (free fall from the last height and speed, carried forward along the course). The panel gives distance and direction from the pilot, GPS coordinates to copy, and a link to map.geo.admin.ch.
- **Recording:** everything is saved to `logs/live/<location>/`. When you disconnect (with *Save the flight* ticked), the flight becomes a normal log of the scene.
- **Training:** the same warnings work in the simulator (*Also warn during training flights*), so you can get used to them before a real flight. *Replay a flight log (test)* plays one of the scene's logs back as if it came from the radio, to try everything without flying.

**Limits**
- The warnings are only as good as the model: trees, cables and terrain finer than the scene's detail are not in it. The live LQ warning is the real safety net, and you still keep visual line of sight as the rules require.
- GPS telemetry arrives a few times per second, so warnings aim at 2–5 s ahead, not the last second.
- The impact zone is an estimate; the last known position is the solid part.
- The warnings need the 3D shadows of the scene (built by default; `refresh-all` for old scenes).


**Pilot position at the field.** The warnings use the *live pilot*: the take-off point (the median of the drone's
GPS positions while it sits on the ground, locked at take-off so it never jumps), or your phone's GPS (*[my
position]*), or a point picked on the map. The line of sight is computed live from there, in the browser, so
taking off away from the location's planned point needs no rebuild. The coloured shadow maps stay those of the
location's point; *[save as this location's pilot]* rebuilds them from the live point (do it at home, it takes a while).

**Altitude when armed.** Betaflight sends the GPS altitude while disarmed and the height above the arming point
while armed (760 m becomes 0). Alpline recognises the second case (an altitude far below the ground) and adds the
ground height at the take-off point.

## Deleting locations

On the map page, *[saved] → [delete]* next to a location (or *[map] → This location → [delete]* in the 3D viewer) deletes it after a confirmation. Nothing is destroyed right away: the location file, its 3D scene and its training flights move to the `deleted/` folder.
- **Undo:** use *Undo* just after deleting, *[restore]* under *Recently deleted*, or `python -m fpv3d restore <name>`.
- **Kept:** the terrain cache (shared by all locations) and your own flight logs outside `logs/sim/` are never touched.

```bash
python -m fpv3d delete teysachaux          # asks for confirmation (-y to skip)
python -m fpv3d restore                    # list what can be restored
python -m fpv3d restore teysachaux
python -m fpv3d deleted --purge            # empty deleted/ for good (--older-than 30 = only old ones)
```

## Routes (corridor locations)

Sometimes you only fly along a line: from your takeoff spot to a summit, or along a ridge. A **route** location keeps only a strip along that line instead of a whole square. That means far fewer tiles to download (a 5 km route with 500 m each side is about 6 km² instead of 50–100 km²), faster builds, and room for finer detail.

- **Create one on the map page:** *[new] → Shape → Route*. Click points along the route, drag the white dots to adjust, and set the width on each side (100 m – 2 km, default 500 m). The first point is also the pilot until you move [pilot]. The preview shows the strip, its tiles (already cached or not), the download size and the area a square would have needed. *Undo point* / *Clear route* fix mistakes.
- **In a location file:**
  ```yaml
  corridor:
    width_m: 500
    points:
      - {lat: 46.5395, lon: 7.0000}
      - {lat: 46.5486, lon: 7.0181}
  ```
  (instead of `center` / `half_size_m`; the pilot defaults to the first point).
- **Build:** only the tiles the strip touches are downloaded in full detail. The signal from the pilot to the strip can cross terrain outside it, so the area between the pilot and the route gets a coarse 10 m bare-ground model; it's small and only used for the signal analysis. Shadows, 3D volumes and buildings are computed for the strip only.
- **Viewer:** only the strip is drawn, with the route as an orange line. *[signal] → Side view along the route* shows a side view along the route:
  - the ground
  - the height below which you have **no line of sight** to the pilot (indigo band)
  - the Fresnel line (amber) and the predicted signal-loss line (red, dashed)
  - the "shadow at X m above ground" height
  - your flight, projected onto the route

  Hover it to read the numbers at any point; a marker appears on the 3D map. It follows antenna / power edits live.

Limit: inside the program the strip is stored in the rectangle around it. A very long diagonal route at very fine detail can still use a lot of memory, and the map page warns you when the box gets large.

## Terrain detail and 3D buildings

A browser can't draw a 0.5 m terrain of several km (an 8 km scene at 0.5 m is 16 000 × 16 000 cells, about 1 GB). The viewer therefore shows:
- **Overview:** the whole map, decimated to about 1500 × 1500 cells. The local server sends only that, not the full file.
- **Sharp close-up:** a patch of about 770 × 770 cells at the scene's full resolution. It follows the point you look at (orbit target, or the chased drone).
- **Sharp photo:** when the scene's resolution is 1 m or finer, the build also downloads the aerial photo at 0.5 m within `detail_radius_m` of the pilot, and the close-up uses it.

*[map] → + Advanced* shows the mesh detail. Turn the close-up off with *Extra detail near the centre of the view*.

**3D buildings:** footprints come from OpenStreetMap (very complete in Switzerland). The ground under each building is the lowest swissALTI3D height under it. On surface-model (`dsm`) scenes, the roof is the median swissSURFACE3D height inside the footprint. Otherwise the height comes from the OSM tags (`height`, `building:levels`) or a default. With *View → Ground → Bare ground + 3D buildings* you get clean blocks on the bare terrain instead of the blurry "blobs" a surface model gives. Click a building for its height. The signal analysis still uses the surface model, which also contains trees.

Location options (`terrain:`): `buildings: true|false`, `ortho_detail_m: auto|0.25|off`, `detail_radius_m: 600`. Existing scenes get buildings and bare ground with `python -m fpv3d refresh-all`.

Buildings come from the public OpenStreetMap servers (Overpass API), which limit how many requests one computer can make in a row. fpv3d retries a busy server and then tries two other public servers. If a scene still ends up without buildings, the viewer says why (*View* tab), and you can retry only the missing ones:
```bash
python -m fpv3d buildings                          # every built scene that has no buildings yet
python -m fpv3d buildings locations/moleson.yaml   # one scene (redone even if it has some)
python -m fpv3d buildings --all                    # redo all of them
```
The same thing is available as the *Buildings* button on the map page ([saved]).

## Terrain cache (memoised levels of detail)

Every 1 km swisstopo tile is downloaded once and resampled once per resolution. Results are kept in `cache/lod/<dtm|dsm|ortho>/<res>m/`, and every later build and location that touches those tiles reuses them. A new resolution of an area you already downloaded is made from the saved downloads, with no network needed. LOS shadow maps are also reused when terrain, pilot and radio settings haven't changed.

```bash
python -m fpv3d prefetch locations/moleson.yaml --res 2 5 10 --ortho-res 1 2   # get several detail levels now, use them later or offline
python -m fpv3d prefetch locations/moleson.yaml --surface both                  # bare ground + trees/buildings
python -m fpv3d build locations/moleson.yaml --resolution 2 --name moleson_2m  # high-detail variant next to the normal scene
python -m fpv3d cache info                                                      # what's cached and how big
python -m fpv3d cache clear --raw                                               # free space, keep the resampled tiles
python -m fpv3d build locations/moleson.yaml --refresh                         # re-download (new swisstopo acquisition)
```

## Switzerland map (click to create locations)

```bash
python -m fpv3d map
```
This opens a map of Switzerland in your browser. It shows:
- every 1 km tile you have already cached, coloured by kind; finer resolution is drawn more opaque
- your locations, as a rectangle for the area and a small [p] tag for the pilot

Click the map to set the pilot and the area, or drag the [pilot] / [+] markers. You can also search for a place. Then pick the size, detail level and radio settings. Before you save, it tells you how many tiles are already cached and roughly how much would be downloaded. **Save & build** creates `locations/<name>.yaml`, builds the scene and links straight to the 3D view. While it builds, the location's 1 km tiles are drawn on the map and fill up as they download: dashed = still to get, blue outline = downloading, bright = just downloaded, dark = already cached, grey = no data. A card shows the steps (Terrain → Photo → Shadows → Logs → Zones), an overall bar, tile counters and the download speed. The full build log is under *Technical details*. The basemap and place search need internet; cached tiles and your locations show either way.

## Training flight (simulator)

In the 3D viewer: *[fly] → Start training flight*. You fly over the real swisstopo terrain with your radio, plugged in by USB in **Joystick** mode, or with the keyboard. The link to your pilot position is computed live with the same model as the build, and shown in an OSD (margin, RSSI and LQ estimate, line of sight). With *Simulate link loss* on:
- the video gets blocky, then freezes on "NO SIGNAL"
- losing the control link triggers failsafe (stage 1, then the quad drops)

Flights are recorded while armed. **Save training flight** stores them in `logs/sim/<scene>/` and adds them as tracks named `<location>_sim_<date>_<time>`. Under *Flight → Compare with* you can pick the real flight: it shows as a dashed line with a ghost drone at the same elapsed time, plus a side-by-side table (distance, height, speed, time without LOS, predicted and logged signal).

Set up the radio with *Radio setup*: detect or pick each axis, then invert if needed. Settings (rates, angle/acro, thrust-to-weight, camera tilt and FOV) are under *Flight model & camera*.

## Drone zones (FOCA)

Every build also downloads the official FOCA/BAZL dataset "Geographical UAS zones" (`ch.bazl.einschraenkungen-drohnen`). It's cached and refreshed after 7 days. The zones touching the map are drawn in the viewer:
- hatched on the terrain, red = prohibited, orange = authorisation required, yellow = conditional
- with walls showing their height limits
- with a clickable list giving rules, validity dates, the authority and a link

The HUD shows the zone the drone is in (inside the zone's height band). Tracks can be coloured by zone, and the comparison table shows the time spent in restricted zones. The simulator warns when you enter a zone. The map page shows the official FOCA layer.

Update only the zones of an existing scene: `python -m fpv3d zones locations/<name>.yaml`

**Informative only**: zones change (events, temporary bans). Always check map.geo.admin.ch or an official app before flying.

## Update every scene at once

```bash
python -m fpv3d refresh-all               # all built scenes: new features, fresh drone zones, tracks kept (terrain reused)
python -m fpv3d refresh-all --zones-only  # only re-download the drone zones (fastest)
python -m fpv3d refresh-all --full        # also rebuild the terrain from the cache
python -m fpv3d refresh-all --missing     # also build locations that were never built
python -m fpv3d refresh-all --only moleson teysachaux
```
The same thing is available as buttons on the map page (*Update all scenes*). One scene failing doesn't stop the others, and a summary is printed at the end.

## Renaming locations and logs

File names are kept plain: lowercase letters, digits, `_` and `-`, with no spaces, accents or emoji. That makes them easy to type, sort and copy. Display titles can contain accents (emoji are removed).

- **In the viewer:** use *[map] → This location → [rename]* to change the title and file name of the location, or *[flights] → [rename]* next to the log picker to rename the selected log.
- **On the map page:** use *[saved] → [rename]* next to a location.

```bash
python -m fpv3d rename location t gruyere_north --title "Gruyère north"   # yaml, scene folder, logs/sim/<name>/
python -m fpv3d rename location moleson --title "Moléson (FR)"           # title only
python -m fpv3d rename log teysachaux teysachaux_sim_2026-10-11_1525 first_ridge_run
python -m fpv3d tidy            # show what would be cleaned (titles, old sim_YYYYMMDD_HHMMSS names)
python -m fpv3d tidy --apply    # do it
```
A rename moves the location file, the built scene, the simulator logs and the processed tracks, so you don't need to rebuild. A log inside `logs/` is renamed on disk too. A log elsewhere (e.g. in Downloads) is never touched: only its name inside fpv3d changes, and later rebuilds keep that name.

## A new spot

```bash
python -m fpv3d new gantrisch --lat 46.712 --lon 7.444 --title "Gantrisch"
# edit locations/gantrisch.yaml (pilot position, radio settings), then
python -m fpv3d build locations/gantrisch.yaml
```

Things you'll want to edit in a location file:

| key | meaning |
|---|---|
| `center`, `half_size_m` | map area (lat/lon or LV95 `e`/`n`) |
| `pilot` | where you stand. Remove lat/lon to use the first GPS fix of the first log |
| `terrain.surface` | `dtm` = bare ground. `dsm` = with trees and buildings (more realistic for 5.8 GHz, bigger download: 0.5 m tiles) |
| `terrain.resolution_m` | 5 m is a good default. 2 m is sharper but heavier |
| `analysis.los_agl_m` | heights above ground to precompute shadow maps for |
| `links` | your radios: power, antenna gains, receiver sensitivity, fade margin |
| `log_options.altitude_mode` | `auto`, `amsl` (GPS altitude), `relative` (baro, 0 at take-off), `agl` |

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

## How the signal model works (and its limits)

1. **Range sphere.** Radius = distance where `Ptx + Gtx + Grx − losses − FSPL(d) = sensitivity + fade margin`.
2. **Line of sight.** For every map cell, a ray goes from your antenna to a drone hovering *N m* above that cell. The ray is sampled against the terrain, including earth curvature with a k = 4/3 refraction factor. The pipeline records the smallest clearance, and that clearance divided by the first-Fresnel-zone radius. Less than 60 % Fresnel clearance is shown amber. Blocked is shown dark.
3. **Predicted margin.** This is FSPL plus a single knife-edge diffraction loss (ITU-R P.526). Black areas or red track samples mean the model expects the link to drop.

It's a planning aid. Multipath, your body and goggles, antenna patterns and polarisation, interference and foliage all matter in reality. `dtm` ignores trees completely. Compare the predicted margin with the logged RSSI/LQ, then tune `fade_margin_db` until the two match for your gear.

## Checks

```bash
python tests/run_all.py             # basics, server, warnings
python tests/run_all.py --browser   # + opens the pages in a hidden browser (needs: pip install playwright; python -m playwright install chromium)
```

- **Basics:** coordinates, log readers, radio maths, the telemetry parser.
- **Server:** the pages load, bad requests are refused, other devices need the PIN and cannot delete or rename, one build per location, cache cleaning keeps used tiles, the https certificate.
- **Warnings:** 26 situations with a fake hill, clock and sound: what the warning says (climb, turn, outside the map, weak signal) and what you hear in each mode (sentence once, climb sound repeating, "Climb" after three, muted groups silent, the lost tone). Needs [Node](https://nodejs.org); without it open `http://localhost:8000/viewer/test/` while Alpline runs. Run them after changing `viewer/warn.js`.
- **Browser:** opens the checks page, the map, the share page and your first location in Full and Lite, and lists page errors. Screenshots in `logs/checks/`. Failed downloads (no internet) are noted, not counted as errors.

Viewer code: `app.js` (scene, replay, panel), `hud.js` (info box), `links.js` (radio editor), `rename.js` (rename / delete), `warn.js` (warnings), `live.js`, `sim.js`, `detail.js`. `drone.js` draws the drone icon (live link indicator, training box, build card, share page, empty pages). Full / Lite / phone is decided once in `theme.js` and handed to the modules by `env.js`. The logo animation (spin-up when a page opens, spinning while something loads or builds) is in `theme.css`; the launcher plays frames made from it by `tools/render_logo_frames.py` (run it again after changing the logo).

## Data

Data: © swisstopo (swissALTI3D, swissSURFACE3D Raster, SWISSIMAGE 10 cm), free under the swisstopo open-data terms (OGD). It is fetched via the STAC API at `data.geo.admin.ch`. To test without internet: `python tests/mock_stac.py` and set `FPV3D_STAC_BASE=http://127.0.0.1:8765/api/stac/v0.9`. That serves synthetic terrain.

Always check the drone rules (FOCA / BAZL map at map.geo.admin.ch) before flying.
