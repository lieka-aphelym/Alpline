# Locations, terrain and maps

[← back to the README](../README.md)

## Map page (click to create locations)

```bash
python -m fpv3d map
```
This opens a map in your browser, on Switzerland at first (move or search to go anywhere). It shows:
- every 1 km tile you have already cached, coloured by kind; finer resolution is drawn more opaque
- your locations, as a rectangle for the area and a small [p] tag for the pilot

Click the map to set the pilot and the area, or drag the [pilot] / [+] markers. You can also search for a place. Then pick the size, detail level and radio settings. Before you save, it tells you how many tiles are already cached and roughly how much would be downloaded. **Save & build** creates `locations/<name>.yaml`, builds the scene and links straight to the 3D view. While it builds, the location's 1 km tiles are drawn on the map and fill up as they download: dashed = still to get, blue outline = downloading, bright = just downloaded, dark = already cached, grey = no data. A card shows the steps (Terrain → Photo → Shadows → Logs → Zones), an overall bar, tile counters and the download speed. The full build log is under *Technical details*. The basemap and place search need internet; cached tiles and your locations show either way. What you type in the search box goes to swisstopo's place search. Places outside Switzerland are found once you tick *also search outside Switzerland* under the box: what you type then also goes to Photon (the OpenStreetMap search run by Komoot). It is off until you tick it, and the choice is remembered. A typed position such as `47.26 11.39` is used as it is and sent nowhere.

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

## Outside Switzerland

A location file whose centre is outside Switzerland builds too:

```yaml
name: nordkette
title: "Innsbruck Nordkette"
center: {lat: 47.305, lon: 11.38}
half_size_m: 2000
pilot: {lat: 47.2867, lon: 11.3986}
terrain: {resolution_m: 10, surface: dtm}
links:
  - {name: "Video 5.8 GHz", freq_mhz: 5800, tx_power_dbm: 14, tx_gain_dbi: 2, rx_gain_dbi: 2, rx_sensitivity_dbm: -85}
```

What is different there:

- **Terrain** comes from the Copernicus worldwide model, measured about every 30 m (swisstopo: 0.5 m). Tree tops and
  roofs are partly in it and there is no bare-ground version, so `dtm` and `dsm` give the same heights. A finer
  `resolution_m` only smooths it. Signal shadows are a rough guide there: a ridge is right, a row of trees is not.
- **The photo** is the Sentinel-2 cloudless satellite mosaic of 2016, about 10 m per pixel (swisstopo: 10 cm): fine
  to recognise valleys, forests and villages, not single trees or paths. A finer `ortho_resolution_m` is ignored
  there, and there is no sharp close-up around the pilot.
- **No drone zones**: check the official drone map of the country you fly in.
- **3D buildings** come from OpenStreetMap, with heights from its tags or a default.
- The **map page** works there too: type a position (`47.26 11.39`) or tick *also search outside Switzerland* and
  search a place, then click, save and build. The
  basemap switches to OpenStreetMap outside Switzerland; a satellite layer is in the layers menu.
- Positions must be lat/lon. The scene uses the UTM grid of the place (shown in the viewer, for example "UTM 32N").

Terrain downloads are 1 x 1 degree files (20 to 50 MB each), kept in `cache/copernicus/` and reused by every
location nearby. The photo comes as small map tiles, kept in `cache/sentinel2/`. `prefetch` fetches both.

Just across the Swiss border (roughly 45.7 to 47.9 north, 5.8 to 10.6 east) a location stays on the Swiss grid:
swisstopo data where it exists, the worldwide model and the satellite photo for the rest.

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
