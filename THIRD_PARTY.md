# Third-party software and data

Alpline itself is free software under the GNU General Public License, version 3 (see [LICENSE](LICENSE)).
It uses the work of others, listed here with their licences.

## In this repository (`viewer/vendor/`)

| What | Licence | Where the text is |
| --- | --- | --- |
| [three.js](https://threejs.org) (`three.core.js`, `three.module.js`, `OrbitControls.js`) | MIT | `viewer/vendor/THREE_LICENSE` |
| [Leaflet](https://leafletjs.com) | BSD 2-Clause | `viewer/vendor/leaflet/LICENSE` |
| [Inter](https://rsms.me/inter/) (variable, Latin subset, from Fontsource) | SIL Open Font License 1.1 | `viewer/vendor/fonts/OFL-Inter.txt` |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) (variable, Latin subset, from Fontsource) | SIL Open Font License 1.1 | `viewer/vendor/fonts/OFL-JetBrainsMono.txt` |
| [QR Code Generator for JavaScript](https://github.com/kazuhikoarase/qrcode-generator) (Kazuhiko Arase) | MIT | header of `viewer/vendor/qrcode.js` |

## Python libraries (installed by `requirements.txt`, and inside the Windows app)

| What | Licence |
| --- | --- |
| [NumPy](https://numpy.org) | BSD 3-Clause |
| [Rasterio](https://github.com/rasterio/rasterio) (with GDAL, PROJ, GEOS and their libraries) | BSD 3-Clause (GDAL and PROJ: MIT) |
| [Pillow](https://python-pillow.org) | MIT-CMU (HPND) |
| [PyYAML](https://pyyaml.org) | MIT |
| [pySerial](https://github.com/pyserial/pyserial) | BSD 3-Clause |
| [orangebox](https://github.com/atomgomba/orangebox) | GPL-3.0 |
| [cryptography](https://cryptography.io) | Apache-2.0 or BSD 3-Clause |
| [Python](https://www.python.org) (inside the Windows app) | PSF License |

The Windows app is made with [PyInstaller](https://pyinstaller.org) (GPL-2.0 with an exception that allows
distributing the built app under any licence). Each library's full licence text is in its folder under
`_internal\` in the installed app, or in `.venv\Lib\site-packages\<name>.dist-info\` in a source set-up.

## Data

Terrain, surface and aerial photos: © [swisstopo](https://www.swisstopo.admin.ch) (swissALTI3D, swissSURFACE3D
Raster, SWISSIMAGE 10 cm, the grey base map), free under the swisstopo open-data terms (OGD), source to be named.

Terrain outside Switzerland: Copernicus DEM GLO-30, read from its public copy on AWS. Produced using Copernicus
WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the
European Union and ESA; all rights reserved. Free to use with this credit, which the viewer shows on such scenes.

France: the aerial photo BD ORTHO (15-20 cm) and the heights RGE ALTI (1 m) of IGN, the French national mapping
agency, read from its Geoplateforme (<https://data.geopf.fr>), under the
[Licence Ouverte / Open License 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) (Etalab), which
asks for the source to be named: "IGN - BD ORTHO" and "IGN - RGE ALTI". The viewer shows these credits on such
scenes.

United States: the bare-ground heights of the USGS 3D Elevation Program (3DEP) and the NAIP aerial photo (USDA
Farm Service Agency), read from The National Map's image services (<https://elevation.nationalmap.gov>,
<https://imagery.nationalmap.gov>). USGS data are in the U.S. public domain (USGS "Copyrights and Credits" page,
read 25 November 2026), and the photo service describes its pictures as public domain; the USGS asks for credit,
so the viewer shows "USGS National Map 3D Elevation Program (3DEP)" and "USGS, USDA, The National Map:
Orthoimagery (NAIP)" on such scenes.

Photo outside Switzerland (France and the United States): the ESA WorldCover Sentinel-2 composite of 2021 (red, green and blue bands), read from
its public copy on AWS, <https://registry.opendata.aws/esa-worldcover-vito-composites/>. © ESA WorldCover project
2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium, under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The viewer shows this credit on such scenes.

Where that picture has nothing (ground under snow all year, or the service cannot be reached), and for the map
layers below: Sentinel-2 cloudless 2016, <https://cloudless.eox.at>, by EOX IT Services GmbH (contains
modified Copernicus Sentinel data 2016), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Only the
2016 mosaic is used: the later years are for non-commercial use only. The viewer shows this credit on such scenes.
The same mosaic is the satellite layer of the map page and the launcher's map outside Switzerland.

Place search outside Switzerland (only when switched on, on the map page): [Photon](https://photon.komoot.io) by
Komoot, on © OpenStreetMap data (ODbL).
Drone zones: Federal Office of Civil Aviation (FOCA / BAZL). Buildings: © OpenStreetMap contributors (ODbL).
None of this data is in the repository: Alpline downloads it to your computer when you build a location.
