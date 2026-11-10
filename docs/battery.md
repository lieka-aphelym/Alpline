# Battery analysis

[← back to the README](../README.md)

Betaflight logs the pack's voltage and current in the blackbox (about 50 times a second); radio logs carry RxBt / Curr
(once a second). Alpline reads them when a blackbox is downloaded or a log is added, also from logs without GPS (those
show only on the packs page). Glitches (a voltage or current spike far from its neighbours) are filtered out.

- **[battery] tab in the 3D viewer**, for the flight being replayed: mAh and Wh used, peak and average current (and C),
  the lowest cell voltage under load and how long it stayed under 3.5 V, the cell voltage at take-off and at landing
  (resting: without the sag), the worst sag and the pack's **internal resistance**. *Sag vs current* shows each
  moment's voltage drop against its current: the slope is the resistance. The pack that flew it is picked here
  (or *+ new pack*: name, cells, capacity, LiPo / LiPo HV / Li-ion), with landing advice for that pack. A **chart under the playback bar**
  follows the replay (cell voltage under load, resting estimate dashed, current, throttle); click it to jump there.
  *[flights] → Colour the path by → Battery: cell voltage / current* colours the 3D path.
- **Packs page** (*[all packs and their health]*, or the launcher's drone page): every pack with its resistance now
  and its trend over its flights, sag at 100 A, mAh per minute at your flying and when to land (80 % of the capacity,
  in mAh and minutes), and flags: *ageing* (resistance up by 40 % since its first flights), *weaker than your other
  packs* of the same type, flights with cells under 3.5 V for more than 5 s. Below: every flight with battery data
  (pick its pack, open it in 3D, see its discharge), the ones without a pack first with *[without a pack]*.
- **LiPo, LiPo HV or Li-ion:** each pack has its type, and the levels follow it. LiPo (4.20 V full) and LiPo HV
  (4.35 V full): low under load 3.5 V/cell, live warnings at 3.3 V under load and 3.4 V resting, a good pack is 2 to
  6 mΩ per cell. Li-ion (18650 / 21700 packs for long range, made to go lower and to sag more): low 3.0 V/cell,
  warnings at 2.9 V under load and 3.1 V resting, good under 20 mΩ per cell. A LiPo landed under 3.35 V/cell resting
  is flagged as too deep (for a flight without a pack: "normal for Li-ion, too deep for a LiPo"); Li-ion and LiPo
  packs are never compared with each other.
- **Notes about a pack:** what happened to it, dated and optionally tied to a flight: crash / hard landing, puffed /
  swollen, damaged wrap / leads / plug, over-discharged, came back hot, flown in the cold, left full, repaired, other,
  with your remark. Add them on the packs page (pick the pack) or from the viewer's [battery] tab (*+ a note about this
  pack*, dated with that flight). They show as marks on the pack's resistance chart and in its list. A swollen pack is
  flagged **retire it** (first flag, ⚠ in the table); after a crash or damage Alpline compares the resistance before
  and after (*resistance up 35 % since* or *no change since*), or says to check it before the next flight. Notes can
  be deleted on the computer only.
- **Older flights:** *[read battery from saved logs]* on the packs page reads the blackbox files kept in
  `logs/blackbox/` again (no drone needed) and gives flights added before the battery analysis their battery data
  (`python -m fpv3d blackbox --saved`).
- **Dates and cell count:** a log made without a GPS fix has no clock; its flight is dated by the download and marked
  ≈. The pencil next to a flight's date corrects it. When the voltage fits two pack sizes (26.1 V is 7 cells by
  Betaflight's rule, and also a full 6S LiPo HV), the battery tab says so until you pick the pack.
- **Charger check:** type what your charger put back in after a flight. Alpline compares it with the mAh the drone
  logged: within 5 % the current sensor is right; otherwise it gives the Betaflight command
  (`set ibata_scale = …`, then `save`).
- **Live flight warnings** (*[fly] → Live flight → Warnings*): pick the pack you fly, the share to land at (80 %) and
  the low level (3.3 V/cell). From the radio's telemetry the voice says *Half pack*, *Land now, 1040 milliamp hours*,
  *Battery low, land* (cells under the low level for 2 s) and *Battery critical, land now* (resting under 3.4 V/cell),
  after a three-note sound (mute it with the *battery* box). The tile shows the cell voltage and the share used. The
  saved live flight is linked to that pack. Replaying a log with battery data uses its real battery.

The resistance is the slope of voltage against current over the flight (V = rest(mAh) − R·I, least squares with the
outliers dropped). It needs some punch-outs (at least ~8 A of spread) and is only reported when believable (1 to
60 mΩ per cell). A good fresh pack is usually 2 to 6 mΩ per cell; cold packs and nearly empty packs read higher.
Limits: the flight controller measures the whole pack, so a single weak cell only shows as more sag; there is no
temperature; mAh are only as good as the current sensor's calibration (use the charger check). The packs and which
pack flew what are kept in `battery/packs.json`, each flight's series in `battery/flights/` (both in backups; the
files page can clear them).

Flights are named by their start minute; two flights from the same minute get the log's number added (`_02`), so
neither replaces the other. The packs file is locked while it is written, so the launcher, the server and a blackbox
download (three separate programs) cannot lose each other's changes.
