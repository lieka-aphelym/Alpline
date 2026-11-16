# Changelog

What changed in each release of Alpline. Newest first.

## Unreleased

- **Launcher map, zoomed out:** once you zoom out a little past Switzerland, the whole map is the satellite
  picture, Switzerland included, instead of a dark Swiss map sitting in the middle of it. Zoom back in and the
  Swiss map returns.
- **Newer satellite photo abroad:** outside Switzerland the photo is now the ESA WorldCover Sentinel-2 picture
  of 2021 (about 10 m) instead of the 2016 one. It is the average of a whole year, so it has no picture where
  snow lies all year (glaciers, the highest summits): those parts, and anything it cannot deliver, are filled
  from the 2016 picture, which stays as the fallback.
- **No more thin black lines in the photo south of Switzerland:** around Mont Blanc and Aosta a 10 to 20 m band
  along some 1 km tile edges stayed empty. Rebuild the location to get the corrected photo.
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
