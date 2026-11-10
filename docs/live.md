# Live flight: telemetry and warnings

[← back to the README](../README.md)

The *Live flight* section of the *[fly]* tab shows the drone live on the 3D map from your radio's telemetry (ELRS / CRSF), warns the pilot before he flies into a zone without line of sight, and marks the last known position plus a likely impact zone if the link is lost.

**Setup (EdgeTX, e.g. RadioMaster TX15)**
1. Install the serial library once: `pip install pyserial`.
2. On the radio, set *SYS → Hardware → USB-VCP* to **Telemetry mirror** (EdgeTX 2.9+; the menu name can differ slightly between versions).
3. Plug the radio in USB and choose **USB Serial (VCP)** when it asks.
4. In the viewer, open *[fly]*, click *[refresh]*, pick the port and click *[connect]*. Connect while the drone is still on the ground: its GPS altitude is then calibrated against the terrain. You can also type an altitude correction yourself.

**What you get**
- **Live drone:** the drone (same marker as in replay, faded while its position is estimated) moves on the map with a trail coloured by LQ, a dashed line shows where it will be in a few seconds, and you see LQ, RSSI, SNR, TX power, battery, flight mode, height above ground, speed, distance and satellites.
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

**If the radio's USB cable drops.** The flight stays open: Alpline says *Radio unplugged, reconnecting*, tries to
reopen the port every second for 30 seconds, and says *Radio back* when the data flows again. The recording goes on
in the same file. Only after 30 seconds without the radio does the live flight end with an error.
