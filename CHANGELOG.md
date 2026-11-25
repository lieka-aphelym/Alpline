# Changelog

What changed in each release of Alpline. Newest first.

## Unreleased

- **Showcase quality:** *Map > Advanced > Quality: showcase* draws the whole area about four times finer (3200 points a
  side instead of 1500: a 6 km area at 2 m is sharp everywhere) and the sharp close-up about seven times larger (4 km at 2 m), with a sharper photo in it.
  For a strong graphics card (about 1 GB of its memory); not offered on a phone or in Lite. Remembered per browser.
- **Sharp close-up in the free-fly and drone views:** the patch of full-detail terrain now follows the ground you
  look at. It used to stay where the orbit view had left it, so flying away showed only the coarse overview.
- **United States in detail:** places in the 48 states, Alaska and Hawaii now get the USGS bare-ground heights
  (3DEP: 1 m where the country was scanned by lidar, which is most of it, 10 m elsewhere) instead of the 30 m
  worldwide model, and the NAIP aerial photo (about 60 cm, instead of the 10 m satellite picture). The photo is
  often a few years old (2017 to 2019 in the places tried). Rebuild an American location to get it.
- **A calmer, more professional look:** Inter for words and JetBrains Mono for figures (both built in, so they work
  offline); yellow is kept for measured values, the selection and the one main button; every fold opens the same
  way. The top bar shows the place's coordinates and the two pages (Locations, 3D viewer) as tabs. The instruments
  say where their figure holds ("In sight within 232 m") and warn when the range covers little of the map. The
  Signal tab starts with your setup, then what the map shows; the legend appears only with the colours on, and
  Undo / Save only once something changed. The flight readout is a cell like the others, "hidden by terrain" is
  violet everywhere, and the playback bar shows where the signal held, was hidden or was lost.
- **Loading screen:** the place's own aerial photo appears blurred and in coarse blocks and turns sharp as the 3D
  view loads, then says "ready".
- **Surroundings without gaps or fog:** the coarse terrain around a location is now sewn to the sharp area (it takes
  the area's heights at the border and blends back over about 150 m), and a short wall under the area's edge fills
  what is left, so the sky no longer shows between them. The surroundings have three clean looks to choose in
  Advanced: contour lines every 50 m (the default), the satellite photo or a pale relief; no more fade and haze, and their outer
  edge is a crisp wall like a model on a table. Rebuild a location to get the sewn border.
- **Online demo:** the 3D viewer runs in the browser on GitHub Pages with a ready-built place (Rochers de Naye)
  and a demo flight, nothing to install. It is rebuilt and published by itself after every merge into `main`.
- **France in full detail:** places in France now get IGN's aerial photo (15-20 cm, instead of the 10 m satellite
  picture) and its 1 m bare-ground heights (instead of the 30 m worldwide model): houses, paths and trees show,
  and signal shadows follow the real ground. Places across the border get the best of each side: swisstopo in
  Switzerland, IGN in France, the worldwide data elsewhere. Rebuild a French location to get it.
- **Keyboard and screen readers (viewer and map page):** every setting, slider and drop-down has a name, buttons
  say what they do and whether they are on or open, and messages (rename, battery, connection, build) are read
  out. The no-fly zone list, saved location names and search results now work with Tab and Enter. Space presses
  a button reached with Tab instead of playing the flight; after a mouse click it still plays. Esc closes the ···
  menu. Control borders on the dark theme are a little lighter so they can be seen.
- **New logo:** an edelweiss that is also a propeller, with three small chevrons for the signal; the icon is the
  same flower on the Swiss red square. The viewer's loading screen now shows the Alps in three layers: a line of
  sight is drawn from the pilot over the summit to the flower, which then spins until the location is ready. The
  logo is back in the viewer's top bar, where it had shrunk to nothing.
- **Launcher map, zoomed out:** once you zoom out a little past Switzerland, the whole map is the satellite
  picture, Switzerland included, instead of a dark Swiss map sitting in the middle of it. Zoom back in and the
  Swiss map returns.
- **Newer satellite photo abroad:** outside Switzerland the photo is now the ESA WorldCover Sentinel-2 picture
  of 2021 (about 10 m) instead of the 2016 one. It is the average of a whole year, so it has no picture where
  snow lies all year (glaciers, the highest summits): those parts, and anything it cannot deliver, are filled
  from the 2016 picture, which stays as the fallback.
- **No more thin black lines in the photo south of Switzerland:** around Mont Blanc and Aosta a 10 to 20 m band
  along some 1 km tile edges stayed empty. Rebuild the location to get the corrected photo.
- **New viewer layout:** a top bar with the place, its coordinates and the camera modes; the tabs with icons on
  the left; the 3D view, no longer covered by the panel; and the instruments: video range, how much stays in sight at the
  chosen height, the ground height and position of the pilot (degrees and grid) and where the heights and photo
  come from. On a phone the layout stays
  as it was, with a slim top bar.
- **New locations map layout:** the map page now looks like the viewer. A top bar holds the name, the place search
  (its results, and the opt-in worldwide search, drop down under it), the position under the mouse, the links to
  the pages and a ··· menu for light / dark and the mode. The tabs (New, Saved, Layers) have icons and their panel
  sits beside the map instead of over it. One setting per row, grouped as location, terrain and radio; the shape
  and what a click sets are square switches; the summary (pilot, ground, area, tiles, size) is a list of figures.
  Plain button labels, square markers on the map, and on a phone the panel is a bottom sheet under the map.
- **Calmer viewer:** on a wide screen it opens on the terrain, with the panel closed until you click a tab. The
  instruments show three figures (video range, in sight, ground at the pilot); the
  position and data are one click away. The training flight starts from the Fly tab. The top bar keeps the place
  and the camera; the area, light / dark and the mode are under its ··· menu.
- **Clean view by default:** a location opens with just the terrain, the photo and the pilot. The signal colours,
  the range bubble and the distance rings are one click away (*Signal* and *Map → Advanced*) and stay on once you
  switch them on; the instruments still give the figures. No-fly zones still show.
- **Digital video systems in the radio setup:** *Signal → Radio range* now offers DJI O4 Air Unit, O4 Air Unit Pro,
  O3 Air Unit (CE and FCC versions) and Walksnail Avatar HD Pro next to the analog setups. Their range is the one
  the maker gives for an open field (for example 6 km for the O4 in CE), instead of an analog receiver's 1 to 2 km.
  Save the setup for the location to recompute its signal shadows.
- **Surroundings:** a location is now built with a coarse ring of terrain around it (as wide as the area on each
  side, 2 to 6 km; worldwide 30 m heights and the 2016 satellite photo), so the peaks and valleys around show and the
  map fades out at the ring's rim instead of at the area's edge. It carries no signal data and is a little greyer
  than the area. Rebuild a location to get it; *Map → Advanced → Surroundings* hides it. Route locations do not
  get one. [cache clean-up] keeps its tiles.
- **The map no longer ends like a cut slab:** the last few hundred metres of the area fade into the sky colour,
  and far terrain is a little hazy, as in real air. *Map → Advanced → Soft edges* turns it off (route locations
  keep their plain strip).
- **Playback bar and instruments:** on a wide screen the playback bar is docked along the bottom of the 3D view
  instead of floating in the middle, and *hide* tucks it away behind a small *playback* button (space still plays
  and pauses). The instruments are a card in the view's top-right corner, as tall as what they show, that folds to
  one line (range and in sight). Both choices are remembered.
- **Launcher map:** Switzerland is the map, cut along its border, with the satellite picture all around it,
  instead of a dark rectangle over the neighbouring countries. The outline is fetched once in the background.
- **Lighter panel:** on a wide screen the tabs keep only the settings. The area, the pilot's source, the data
  credits and the signal sentence moved to the column; the camera help is a quiet line on the 3D view. One row per
  setting with its switch on the right, more space between groups, and buttons without the [brackets].
- **Shorter info box in the viewer:** the data credits are folded into one line, *Data credits*, that opens
  with a click, instead of filling the top of the panel.
- **Easier to read:** text in the viewer's panel is one size larger (nothing under 11 px any more), the help
  texts are a little brighter, and the info box uses the normal text font instead of the figures one.
- **Neutral examples:** the search box and the name fields no longer suggest Swiss places.

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
