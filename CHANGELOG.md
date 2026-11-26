# Changelog

What changed in each release of Alpline. Newest first.

## Unreleased

- **Buildings now block the signal.** The 3D buildings used to be drawn only: on a bare-ground scene (France, the
  United States, Switzerland with `surface: dtm`) a drone between tall blocks looked in sight. The signal shadows,
  the 3D blind-spot volumes, "in sight", the flights' line of sight and the live checks of the simulator and Fly
  now count them, while heights above ground are still measured from the street. A pilot point that falls inside a
  building now stands on its roof, and the instruments say so. In a dense city this is much more pessimistic than
  before, and still a simplification: building heights come from OpenStreetMap (or a default of about 8 m), and
  reflections off walls, which often keep a weak link around a corner, are not modelled. **Rebuild a location** to
  get it (the tiles and buildings already downloaded are reused).
- **No more flash of the old loading screen.** Opening a location showed the drawn Alps for a moment before the
  place's photo: they stayed while the viewer started, and until the whole photo (up to 10 MB and more) was
  downloaded and decoded. Now nothing is drawn until the location is read; then the photo's frame comes, filled
  almost at once with a small copy from the local server. The drawn Alps are kept for a place without a photo.
- **The logo's heart is now a yellow triangle, point down.** The flower has three blades, and the old four-sided
  square could not sit evenly among them: it covered the top blade and looked pushed up. The triangle keeps the same
  gap to all three. The icon, the logos, the launcher's animation and the installer icon are all redrawn from the
  same geometry.
- **A start-up screen.** The installed app now shows a picture the moment it is started (the flower and the name,
  with the current step written under it), instead of nothing for the few seconds a cold start takes. The launcher's
  window then opens with a short start-up screen: the photo of the place you selected last, with a line that fills
  as the launcher gets ready. It goes by itself within three seconds, or at a click or a key.

## 1.2.0 (November 2026)

France and the United States now get their national terrain and aerial photos, the viewer has a calmer, more
professional look, and Alpline can be tried in the browser without installing anything. Elsewhere outside
Switzerland the terrain is still the coarse worldwide model. **Rebuild a location** to get what is new for it (the
French or American data, the sewn surroundings, the corrected photo south of Switzerland): the first rebuild
downloads its tiles again.

**Terrain and photo**

- **France in full detail:** places in France now get IGN's aerial photo (15-20 cm, instead of the 10 m satellite
  picture) and its 1 m bare-ground heights (instead of the 30 m worldwide model): houses, paths and trees show,
  and signal shadows follow the real ground. Places across the border get the best of each side: swisstopo in
  Switzerland, IGN in France, the worldwide data elsewhere.
- **United States in detail:** places in the 48 states, Alaska and Hawaii now get the USGS bare-ground heights
  (3DEP: 1 m where the country was scanned by lidar, which is most of it, 10 m elsewhere) and the NAIP aerial
  photo (about 60 cm). The photo is often a few years old (2017 to 2019 in the places tried, 2013 in Hawaii).
- **Newer satellite photo elsewhere abroad:** the ESA WorldCover Sentinel-2 picture of 2021 (about 10 m) instead of
  the 2016 one. It is the average of a whole year, so where snow lies all year (glaciers, the highest summits) it
  has no picture: those parts come from the 2016 picture, which stays as the fallback.
- **No more thin black lines in the photo south of Switzerland:** around Mont Blanc and Aosta a 10 to 20 m band
  along some 1 km tile edges stayed empty.
- **Surroundings:** a location is now built with a coarse ring of terrain around it (as wide as the area on each
  side, 2 to 6 km, from the worldwide data), so the peaks and valleys around show. It is sewn to the area with no
  gap (it takes the area's heights at the border and blends back over about 150 m) and ends in a crisp wall, like
  a model on a table. Three looks in *Map > Advanced > Surroundings*: contour lines every 50 m (the default), the
  satellite photo or a pale relief, or off. It carries no signal data. Route locations do not get one.

**The viewer**

- **A calmer, more professional look:** Inter for words and JetBrains Mono for figures (both built in, so they work
  offline); yellow is kept for measured values, the selection and the one main button; one setting per row, every
  fold opens the same way, and text is a size larger. A top bar holds the place, its coordinates, the camera modes
  and the two pages (Locations, 3D viewer) as tabs; the tabs with icons are on the left, and on a wide screen the
  view opens on the terrain with the panel closed until you click a tab. On a phone the layout stays as it was.
- **Instruments:** a card in the view's corner gives the video range, how much stays in sight within it at the
  chosen height ("In sight within 232 m", with a warning when the range covers little of the map) and the ground
  at the pilot; position and data credits are one click away. It folds to one line.
- **Clean view by default:** a location opens with just the terrain, the photo and the pilot. The signal colours,
  the range bubble and the distance rings are one click away and stay on once you switch them on. The Signal tab
  starts with your setup, then what the map shows. No-fly zones still show.
- **Playback bar:** docked along the bottom of the view on a wide screen, coloured by where the signal held, was
  hidden by terrain (violet everywhere now) or was lost; *hide* tucks it away.
- **Loading screen:** the place's own aerial photo appears blurred and in coarse blocks and turns sharp as the 3D
  view loads, then says "ready".
- **Sharp close-up in the free-fly and drone views:** the patch of full-detail terrain now follows the ground you
  look at. It used to stay where the orbit view had left it.
- **Showcase quality:** *Map > Advanced > Quality: showcase* draws the whole area about four times finer (3200
  points a side instead of 1500: a 6 km area at 2 m is sharp everywhere) and the sharp close-up about seven times
  larger. For a strong graphics card (about 1 GB of its memory); not offered on a phone or in Lite.
- **Digital video systems in the radio setup:** *Signal > Radio range* now offers DJI O4 Air Unit, O4 Air Unit Pro,
  O3 Air Unit (CE and FCC versions) and Walksnail Avatar HD Pro next to the analog setups. Their range is the one
  the maker gives for an open field (for example 6 km for the O4 in CE). Save the setup for the location to
  recompute its signal shadows.
- **Keyboard and screen readers (viewer and map page):** every setting, slider and drop-down has a name, buttons
  say what they do and whether they are on or open, and messages are read out. Lists and search results work with
  Tab and Enter. Space presses a button reached with Tab instead of playing the flight; Esc closes the ··· menu.

**Map page, launcher, brand**

- **New locations map layout:** the map page now looks like the viewer: a top bar with the name, the place search
  and the position under the mouse; New, Saved and Layers tabs beside the map; one setting per row, grouped as
  location, terrain and radio. On a phone the panel is a sheet under the map.
- **Launcher map:** Switzerland is the map, cut along its border, with the satellite picture all around it; zoomed
  out past Switzerland, the whole map is the satellite picture.
- **New logo:** an edelweiss that is also a propeller, with three small chevrons for the signal; the icon is the
  same flower on the Swiss red square.
- **Online demo:** the 3D viewer runs in the browser at <https://lieka-aphelym.github.io/Alpline/>, with a
  ready-built place (Rochers de Naye) and a demo flight. It has no building, no live flight and no sharp close-up.

## 1.1.0 (November 2026)

Alpline now works outside Switzerland.

- **Locations anywhere in the world:** a location outside Switzerland builds from the Copernicus worldwide
  elevation model (about 30 m), with the Sentinel-2 cloudless satellite photo of 2016 (about 10 m). Signal shadows,
  flight replay, live flight and the training flight work on it; 3D buildings take their heights from
  OpenStreetMap. This is a first step: the terrain is much coarser than swisstopo's (a ridge is right, a row of
  trees is not), and there are no drone zones for other countries yet. Swiss locations keep swisstopo data.
- **Maps for the whole world:** the map page creates and shows locations anywhere: it switches to OpenStreetMap
  (or a satellite layer) outside Switzerland, takes a position such as `47.26 11.39`, finds places worldwide once
  you switch that on (it sends what you type to Photon, the OpenStreetMap search; off by default),
  and gives the ground height there. The launcher's map zooms out to the whole world, as a satellite picture
  around the Swiss map.
- **OpenStreetMap layer showing "Access blocked" tiles:** the map page now tells OpenStreetMap which page asks for
  its tiles (only the address of your own Alpline server, never the PIN link), as its usage policy requires. If
  OpenStreetMap still does not load abroad, the map shows the satellite layer instead.
- **Launcher map:** it downloads its map once more after this update (its stored tiles changed).
- **Cache clean-up covers the worldwide data:** `cache prune`, `cache clear` and `cache info` (and the launcher's
  *[clean unused tiles]*) now handle the worldwide model and photo too.
- **Swiss locations at the border:** terrain across the border is now real (worldwide model) instead of a guess
  from the last Swiss heights, and the photo there is the satellite one instead of black.

## 1.0.0 (November 2026)

First public release.

- **3D locations from swisstopo open data:** any place in Switzerland, built from swissALTI3D / swissSURFACE3D and
  SWISSIMAGE, with 3D buildings and the FOCA drone zones.
- **Signal planning:** range spheres per radio link, the signal shadow ("dark zone") for several flying heights,
  predicted link margin with terrain diffraction.
- **Flight replay:** EdgeTX / OpenTX telemetry, Betaflight / INAV blackbox, GPX and plain CSV; the path coloured by
  line of sight, margin, height or any logged value; flight video next to the 3D view.
- **Blackbox straight from the drone** over USB, each flight added to the location it was flown at.
- **Live flight:** the drone on the map from the radio's telemetry, with line-of-sight and battery warnings.
- **Battery analysis:** packs, internal resistance, health over time, notes.
- **Training flight:** a simulator on your own locations.
- **Launcher:** Switzerland map of your locations, drone and radio detection, phone sharing with a PIN and https,
  self-checks, file clean-up, backup and restore.
- **Full and Lite modes,** dark and light themes, a phone layout that installs as an app.
- **Windows installer** (`AlplineSetup.exe`), for your user only, no administrator rights.
