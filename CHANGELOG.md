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
- **Robot camera:** a Raspberry Pi with a camera rides on the robot and streams live video.
  - **On the Pi:** `pi/powershock_cam.py` uses only the standard library. It works with `rpicam-vid`, `libcamera-vid` or `raspivid`, needs an access key for every request, and has a `--test` pattern mode.
  - **In the console:** the Robot page's 3D view switches between **Brick** and **Camera**, and **Connection → Camera** sets it up.
  - **Relay:** the console relays the video, so the page only ever talks to the console.
  - **Setup guide:** `docs/CAMERA.md`.
  - **Full screen:** the Camera view goes full screen with a button, F or a double-click, and driving keeps working there. A small overlay shows whether the motors are on.
  - **Own window:** a button opens just the video in a separate window (`/camera`), e.g. for a second monitor. Clicking into it takes the focus from the console, which switches the motors off; click back in the console to drive.
- **Controller colour swatches** replace the colour dropdown on the Robot page.

### Changed
- **3D DualShock 4 rebuilt from reference drawings:**
  - **Outline:** traced from the Wikimedia Commons layout drawing (162 mm wide).
  - **Shell:** one smooth surface. The grips flow out of the body and bend down, and the stick bosses and button pods are blended in.
  - **Parts:** every part sits where it is on the real pad, sized to match. The D-pad has four separate arrows, and the touchpad is full size.
  - **View:** the default view shows the top of the pad.
- **3D EV3 brick** matched to a photo of the real one:
  - Real proportions (about 76 × 119 × 48 mm).
  - A raised light-grey screen housing that steps up from the white body.
  - The seam line between the screen and the buttons.
  - White sides with Technic holes, and a grey EV3 band along the bottom.
- **Devices list** shows live readings from IR, ultrasonic, colour and gyro sensors.
- **Controller legend** chips are drawn as single pills again; they had a pill inside a pill.
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
