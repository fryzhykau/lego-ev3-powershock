# Changelog

All notable changes to PowerShock. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## Versioning

- **One version for the whole app.** It lives in [`VERSION`](VERSION). The console reads it (`pc/version.py`), and `build.ps1` stamps it into every brick program.
- **The brick reports its version.** `powershock-wifi.jar` sends `V <version>` when the console connects and shows it on the brick's screen. The Program page compares it with the laptop's version.
- **Before 1.0.0**, a minor version (0.**8**.0) may change the protocol between the console and the brick, so upload the new build after updating. Patch versions (0.7.**1**) are fixes only.

### Making a release

1. Move the items under **Unreleased** into a new section `## [x.y.z] - YYYY-MM-DD`.
2. Put the same `x.y.z` in `VERSION`.
3. Run `.\build.ps1` and the tests: `cd pc; python -m unittest`.
4. Commit, then tag it: `git tag vx.y.z`.

## [Unreleased]

### Added
- **Map page:** a live 3D map of what the robot's sensors find while it drives, seen from behind the robot or from above.
  - **Position:** worked out from the wheel motors' angles and the robot's size. In car layouts the steering angle is used too, and a gyro, if one is plugged in, gives the heading.
  - **Walls and obstacles:** the infrared or ultrasonic sensor marks them on an occupancy grid. Each cell keeps a score, so one stray reading doesn't draw a wall.
  - **Floor colours:** painted by the colour sensor.
  - **Robot size:** wheel diameter, wheel spacing, axle spacing, steering ratio and sensor positions, saved to `pc/worldmap.json`.
- **Brick program:** a sensor thread (`Sensors.java`) reads IR, ultrasonic, colour and gyro sensors as they are plugged in. Their readings go to the console in the status line (`s1=ir:37`, `s3=col:5`, …). Older consoles ignore them.
- **Practice brick** now has colour and infrared sensors and drives around a small room with two boxes, blue tape and a red mat.
- **Tests** for odometry, the grid, sensor parsing and the practice room.

### Changed
- **3D DualShock 4** closer to the real controller:
  - Slimmer grips that taper and splay outwards.
  - A thinner shell with a tighter edge.
  - A smaller D-pad in its own recess, and slightly smaller face buttons.
  - The USB port, headset jack and extension port.
  - The whole controller fits in view.
- **3D EV3 brick** has its real proportions (about 76 × 119 × 48 mm). It is taller and deeper than before, without the stray line under the screen.
- **Brick view:** the brick and its motors and sensors fit the card on wide screens. Unchecked ports show just their letter, so their labels no longer overlap.
- **README screenshots** show the 3D brick properly.

## [0.7.0] - 2026-11-26

### Added
- **App versioning**:
  - `VERSION`, this changelog and `pc/version.py`.
  - The brick program reports its version (`V` line), and the console shows both.
- **Controller page**:
  - Step-by-step pairing for Bluetooth and USB, which ticks itself once the controller is seen.
  - What to do when the controller is asleep.
  - Battery, model and firmware, read through Windows (`pc/ds4_hid.py`), with no browser device picker.
- **Stick calibration**: **Calibrate** (rest position and full range), plus dead-zone and response-curve sliders, and **Reset**.
- **Status bar**: the controller's battery.
- **Controls page**: steering ports get a **Centre** control (nudge, **Set centre here**, **Go to 0°**).
- **`pc/tools/extract_libs.py`** copies the three jars the build needs from your own leJOS SD card.
- **Tests** for the link to the brick, WiFi setup and stick calibration.
- **Privacy check** (`pc/tools/privacy_check.py`, also run by the tests): it stops addresses, network names, secrets and SD-card files from being published.
- **Contributor guides:**
  - `AGENTS.md`: rules for people and coding agents.
  - `CLAUDE.md`.
- **README** with screenshots.

### Changed
- **Page layouts**:
  - Robot, Brick, Controller, Controls, Gearing and Connection were reworked.
  - Setup steps sit behind buttons instead of always-open cards.
- **Stop button**: clearer, and it shows when the motors are live.
- **README**: rewritten.

### Fixed
- **Motors off when the link drops**:
  - **Motors on** switches off when the link to the brick drops or the controller disconnects.
  - The robot no longer drives off by itself when the link comes back.
- **"Not used" ports**: a port switched to "Not used" while moving now stops.
- **Saving settings while driving** no longer re-centres the steering or drops the throttle.
- **Connections**:
  - Only one connection to the brick is opened at a time.
  - A brick that stops answering is dropped within 1.5 s.
  - Old commands no longer pile up during a WiFi stall.
- **Stop** can no longer be undone by a late input message.
- **Brick off**: when the brick is switched off, the console says "Not answering" instead of showing it as connected.
- **WiFi setup** works with network names that contain non-ASCII characters.

### Security
- **The console**:
  - answers only its own page
  - checks `Host` and `Origin`
  - needs its own header on every `/api/` call
  - limits request size
- **Brick program** (`powershock-wifi.jar`):
  - Lines are capped at 256 characters, and at most 32 motor tests can be queued.
  - Test turns are capped at ±3600° with a time limit, and steering angles at ±720°.
  - A silent client is dropped after 5 s.
  - Status is sent from its own thread, so a stuck connection can't block the safety stop.
- **SSH helper**: its temporary password file is removed on exit.

## [0.6.0] - 2026-11-25

### Added
- **Controls mapping**:
  - The console sends per-port commands (`P A=s:40 B=p:30:60 C=- D=-`): speed or steering angle for each motor port, with smoothing.
  - Presets: **Tank**, **Car**, **Fit to my motors**.
  - A `zero` test command sets a steering centre.
- **Gearing page**: speed vs. force with standard LEGO gears, in 3D.
- **Robot page**: a 3D DualShock 4 (three.js r187, vendored, MIT).

## [0.5.0] - 2026-11-25

### Added
- **Motor tests**:
  - `M <port> run|rotate|stop|zero` from the console's Devices panel.
  - Held runs stop 0.4 s after the last repeat.

## [0.4.0] - 2026-11-25

### Added
- **Hot-plug motors**:
  - A port is claimed only once a motor is detected there; large or medium is chosen by the detected type.
  - Unused ports keep detecting.

## [0.3.0] - 2026-11-25

### Added
- **Live status to the console** (`T ...` lines, 4 times a second): battery, what is plugged into each port, motor angles and speeds.
- **The web console** (`pc/ev3_console.py`):
  - Connection over Bluetooth or WiFi.
  - Brick details over SSH; brick WiFi setup.
  - Build and upload of the brick program.
  - A practice brick.

## [0.2.0] - 2026-11-25

### Added
- **Port check program** (`powershock-ports.jar`), printing JSON.
- **Motor ports released** when the receiver is stopped, so port detection keeps working.

## [0.1.0] - 2026-11-25

### Added
- **The first version**:
  - The WiFi/Bluetooth-network receiver (`l r a` lines on port 5000, 500 ms safety stop).
  - An experimental direct-Bluetooth DS4 driver over L2CAP via JNA.
  - Tank mixing.
  - A pygame client for the laptop.

[Unreleased]: https://github.com/fryzhykau/lego-ev3-powershock/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/fryzhykau/lego-ev3-powershock/releases/tag/v0.7.0
