# Training flight (simulator)

[← back to the README](../README.md)

In the 3D viewer: *[fly] → Start training flight*. You fly over the real swisstopo terrain with your radio, plugged in by USB in **Joystick** mode, or with the keyboard. The link to your pilot position is computed live with the same model as the build, and shown in an OSD (margin, RSSI and LQ estimate, line of sight). With *Simulate link loss* on:
- the video gets blocky, then freezes on "NO SIGNAL"
- losing the control link triggers failsafe (stage 1, then the quad drops)

Flights are recorded while armed. **Save training flight** stores them in `logs/sim/<scene>/` and adds them as tracks named `<location>_sim_<date>_<time>`. Under *Flight → Compare with* you can pick the real flight: it shows as a dashed line with a ghost drone at the same elapsed time, plus a side-by-side table (distance, height, speed, time without LOS, predicted and logged signal).

Set up the radio with *Radio setup*: detect or pick each axis, then invert if needed. Settings (rates, angle/acro, thrust-to-weight, camera tilt and FOV) are under *Drone and camera settings*.

**How it flies** (`viewer/simphysics.js`, checked by `tests/test_sim.mjs`):
- **What you see is what you hit:** the ground under the drone is the sharp terrain shown around it (with trees when
  the map shows the surface model), and the 3D buildings: land on a roof, or crash into a wall (a slow touch is a bump,
  more than ~15 km/h a crash). The sharp terrain follows the drone, loaded a little ahead in the direction of flight.
- **Battery:** the voltage drops as the pack empties and sags when you punch (OSD: volts per cell and %, "BATTERY LOW —
  LAND" near the end); an empty pack can't hold a hover. *Pack lasts … min hovering* sets the capacity (the presets have
  typical values; a mixed flight lasts about two thirds of it).
- **Throttle mid / expo** like Betaflight's `thr_mid` / `thr_expo`: copy yours so the throttle feels the same.
- **Propwash:** descending into your own wake with throttle on shakes the quad (strength adjustable).
- **Ground effect** close to the ground, and more drag through the prop disk than sideways (it falls flat slower).
- **Motor sound:** pitch and loudness follow the throttle, air noise follows the speed (volume and on/off in the settings).
- **Smooth:** the drawing resolution drops a little when frames get slow and comes back when there is room (*Keep it smooth*).

These are under *Battery, throttle and feel*.
