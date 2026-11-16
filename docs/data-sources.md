# Data sources: what Alpline uses, and what it could use next

[← back to the README](../README.md)

Alpline builds a scene from two things: **heights** (how high the ground is) and a **photo** from above. This page
lists where they come from today and the open data that could make places outside Switzerland better. It is a
working list for choosing what to add next, not a promise.

**How to read the "Checked" column.** *Checked* means the licence or access was looked up on 16 November 2026 (the
source is linked). *From memory* means it is believed to be so but was not looked up: read the provider's own page
before writing any code against it. A licence must allow free use for any purpose, with a credit at most:
"non-commercial" licences are not usable next to Alpline's GPL-3 licence.

## In use today

| What | Where | Detail | Licence |
|---|---|---|---|
| Heights, Switzerland | swisstopo swissALTI3D, swissSURFACE3D | 0.5 m | swisstopo open data, credit |
| Photo, Switzerland | swisstopo SWISSIMAGE | 10 cm | swisstopo open data, credit |
| Heights, rest of the world | Copernicus DEM GLO-30 | about 30 m | free, credit required |
| Photo, rest of the world | ESA WorldCover Sentinel-2 composite **2021** | about 10 m | CC BY 4.0 |
| Photo, where the 2021 one has none | Sentinel-2 cloudless **2016** by EOX | about 10 m | CC BY 4.0 |

## A newer photo of the whole planet

The 2016 mosaic was the only photo until the WorldCover picture of 2021 replaced it (first row, in use now).
These are the options that were looked at, best first.

| Option | Year | Detail | Account | Licence | Checked | Notes |
|---|---|---|---|---|---|---|
| **ESA WorldCover Sentinel-2 composite** | 2021 (also 2020) | 10 m | none | CC BY 4.0 | Checked, **in use** | One-year median picture, 1 x 1 degree files on AWS (`s3://esa-worldcover-s2/`), the same shape as the Copernicus heights Alpline already reads. The files themselves, the AWS listing and the project's page all state CC BY 4.0. It has no pixels where snow lies all year (glaciers): Alpline fills those from the 2016 mosaic. [AWS listing](https://registry.opendata.aws/esa-worldcover-vito-composites/) |
| **Sentinel-2 cloudless 2017** by EOX | 2017 | 10 m | none | CC BY 4.0 | Checked | Same service as today, one word to change. Only one year newer. The provider's own service description gives 2016 and 2017 as CC BY 4.0. |
| Sentinel-2 cloudless 2018 to 2025 by EOX | up to 2025 | 10 m | none | **CC BY-NC-SA 4.0** | Checked | Not usable: non-commercial. The provider sells a commercial licence. |
| **Single Sentinel-2 scenes** through Earth Search | days old | 10 m | none | Copernicus Sentinel terms (free, credit) | Access checked, licence text not read | The freshest possible, but raw: Alpline would pick the least cloudy recent scene for each place itself (the catalogue gives the cloud cover of each scene). Clouds, haze and snow can remain. [Earth Search](https://github.com/Element84/earth-search), [AWS listing](https://registry.opendata.aws/sentinel-2-l2a-cogs/) |
| Copernicus quarterly cloud-free mosaics | every 3 months, to now | 10 m | **yes** (free) | Copernicus Sentinel terms | Checked | The best official product, but it needs a Copernicus account and its keys, which Alpline has avoided so far. [Copernicus Data Space](https://dataspace.copernicus.eu/node/883) |
| Earth Genome yearly mosaics | 2025 to 2026 | 10 m | none | **unclear** | Checked | Announced as Creative Commons, but its own catalogue says "proprietary". Not usable until that is settled. [Announcement](https://www.earthgenome.org/blog/announcing-public-access-to-our-global-cloud-free-imagery-archive) |
| Commercial map photos (Esri, Google, Bing, Mapbox) | recent | under 1 m | key | not open | From memory | Their terms forbid keeping copies for offline use, which is what Alpline does. |

**Suggested path:** WorldCover 2021 as the new default once its terms are read (five years newer, one clean
picture, no account); single recent scenes later, as a choice per location for people who want this year's picture
and accept clouds.

## Sharper heights and photos, country by country

Since June 2024 a European rule (Implementing Regulation (EU) 2023/138, "high-value datasets") requires every EU
country to publish its elevation data and aerial photos free of charge under CC BY 4.0 or freer. That is why so
many European rows below are open. Not every country has finished. [The regulation](https://eur-lex.europa.eu/eli/reg_impl/2023/138/oj)

### Checked

| Country | Heights | Photo | Licence | Notes |
|---|---|---|---|---|
| **France** | IGN LiDAR HD, 0.5 m, 1 km GeoTIFF tiles; coverage of the country still being completed | BD ORTHO, 20 cm (from memory) | Licence Ouverte / Etalab 2.0 (credit) | Some tiles are withheld (areas where aerial pictures are forbidden). [data.gouv.fr](https://www.data.gouv.fr/datasets/mnt-lidar-hd) |
| **Austria** | BEV ALS DTM, 1 m, whole country, GeoTIFF; a new country-wide mosaic each year | BEV orthophotos are published as open data; licence text not found | CC BY 4.0 (heights) | Stated accuracy 0.5 m, less in high mountains. Download from data.bev.gv.at. [Metadata record](https://inspire-geoportal.ec.europa.eu/srv/api/records/97908eb1-c386-42b7-bfab-4cf909058e30) |
| **Italy** | TINITALY 1.1, 10 m, whole country, GeoTIFF | none national | CC BY 4.0, with a set citation | Three times finer than the worldwide model. Regions publish finer lidar separately. [Download page](https://tinitaly.pi.ingv.it/Download_Area1_1.html) |
| **Czechia** | ČÚZK DMR 5G (bare ground) | orthophoto: licence not confirmed | CC BY 4.0 (heights) | Open data since late 2023, through the office's download services. [ČÚZK open data](https://www.cuzk.gov.cz/Uvod/Produkty-a-sluzby/Otevrena-data/Otevrena-data-zakladni-informace.aspx) |
| **Iceland** | ÍslandsDEM, 2 m | some orthomosaics | CC BY 4.0 on some records, unclear on others | The national records disagree on how the licence is stated: read the record of the exact download. [Record](https://gatt.natt.is/geonetwork/srv/api/records/9534cc67-1293-4677-a185-2de87fcb5670) |

### From memory: to be checked before use

**Europe**

| Country | Heights | Photo | Believed licence |
|---|---|---|---|
| Germany | 1 m per federal state; most states are now open (for example North Rhine-Westphalia, Bavaria, Baden-Württemberg, Saxony, Thuringia, Berlin, Hamburg), each with its own service | per state, 20 to 40 cm | mostly "Datenlizenz Deutschland" or CC BY |
| Spain | CNIG MDT02 and MDT05 (2 m, 5 m) | PNOA, 25 to 50 cm | CC BY 4.0 |
| Portugal | national lidar being published | national orthophotos | open |
| United Kingdom | England: Environment Agency lidar, 1 m; Scotland and Wales have their own; OS Terrain 50 for all | not open | Open Government Licence |
| Ireland | partial lidar | not open | CC BY |
| Netherlands | AHN, 0.5 m | national aerial photo, 8 to 25 cm | CC0 (heights), CC BY (photo) |
| Belgium | Flanders 1 m, Wallonia 1 m, separate services | per region | open |
| Luxembourg | lidar, 0.5 m | orthophotos | CC0 |
| Denmark | DHM, 0.4 m | orthophotos | free, a free account for some services |
| Norway | 1 m | not fully open | CC BY 4.0 |
| Sweden | 1 m, opened recently | orthophotos, opened recently | CC0 or CC BY |
| Finland | 2 m | orthophotos | CC BY 4.0 |
| Estonia, Latvia, Lithuania | 1 m lidar | orthophotos | open |
| Poland | 1 m | orthophotos | open since 2020 |
| Slovakia | DMR 5.0, 1 m | orthophotos | open |
| Slovenia | lidar, 1 m | orthophotos | open |
| Liechtenstein | covered by swisstopo already | | |

**Rest of the world**

| Country or area | Heights | Photo | Believed licence |
|---|---|---|---|
| United States | USGS 3DEP: 10 m everywhere, 1 m for most of the country | NAIP, 0.6 m, every 2 to 3 years | public domain |
| Canada | HRDEM, 1 to 2 m, the populated south | none national | Open Government Licence Canada |
| Mexico | INEGI, 5 m in parts | INEGI orthophotos, older | free |
| Australia | national 5 m, 1 m in parts (the "ELVIS" portal) | per state | CC BY 4.0 |
| New Zealand | LINZ, 1 m by region | LINZ aerial photos, 10 to 40 cm, on AWS without an account | CC BY 4.0 |
| Japan | GSI, 5 m and 10 m | GSI seamless photo | free with credit |
| Arctic and Antarctic | ArcticDEM and REMA, 2 m | none | open |

**Worldwide alternatives to Copernicus** (none better for Alpline): SRTM / NASADEM (30 m, needs a NASA account),
ALOS AW3D30 (30 m, needs registration), FABDEM (30 m bare ground, but non-commercial), TanDEM-X 12 m (not open).

## What a country needs before it is worth adding

1. **Its licence read on the provider's own page**, and the exact credit it asks for.
2. **Access without an account**, by a stable address per file or a catalogue that can be asked by position.
3. **Files Alpline can read**: GeoTIFF best; a web-map tile service is fine for photos.
4. **Whole-country coverage**, or a clear way to know where there is none (the worldwide model fills the gaps).
5. **Drone zones** for the same country, if they are published: terrain and zones together make a country as
   useful as Switzerland is today.

By these, the best first candidates are **Austria** (1 m, one licence, direct files), **Italy** (one 10 m model,
simple) and **France** (very fine, but coverage still growing and tiles withheld in places). Czechia and Iceland are
the places already flown with Alpline, which is a reason of its own.
