# Changelog

What changed in each release of Alpline. Newest first.

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
