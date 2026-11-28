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
- **The camera on the map:** a camera button in the top right corner of the Driving page's map (or **C**) shows the robot's camera there, picture-in-picture, so you can watch the map and the road at once. Click the picture for full screen; the page remembers whether it's open, and the video runs only while it's shown.
- **Camera colours:** on the Pi page, **Colours** can be set to **No infrared filter** for a camera whose picture looks pink or purple. The Pi's camera program then uses the camera's own NoIR tuning and keeps the choice. Needs the updated `pi/powershock_cam.py` on the Pi.

### Changed
- **The Driving tab** has a steering wheel icon.
- **The live map takes a fifth less room** on screens 1280 px wide or less, like the other 3D views.
- **New screenshots in the README** for every page, including the Pi page, the robot size form, and the brick's details on Setup.
- **The robot size form** is in three groups (wheels and drive, sensors, camera), each with a small drawing whose line lights up for the box you're editing; every box shows its unit (mm, °, ×, g) and a one-line hint.
- **The brick's details** on the Setup page are three rows (Software, Bluetooth, WiFi), each with an icon, its state, one main value and small labelled chips. The link this laptop is using is marked **In use**, and WiFi shows the brick's signal.
- **The Map is part of the Driving page:** the live map, with its readout and the sensors beside it, sits on top, and how the robot drives (speed boost, the obstacle brake, the car's limits, the motor ports) below. The Map tab is gone; old links to it open Driving. The brake's live state shows once, by the map.
- **The Brick card starts folded** to one line: battery, how it's connected, the program, and a square per port coloured by what's in it. The arrow opens the 3D brick, and the page remembers.
- **The Your robot drawing is clickable:** the Pi camera opens the Pi page, a motor its card on the Driving page, a sensor its row in Devices, the brick the Setup page, and the car the size form.

### Fixed
- **Stop requires turning Motors on again.** Late controller, motor test and calibration commands from the stopped session are refused. If the page goes quiet, active motor tests and calibration stop too.
- **Practice uses its own controls, robot sizes and calibration.** An explicit copy action can transfer controls to the brick profile.
- **Brake coverage required** blocks driving in directions without a usable sensor or camera reading and shows the missing coverage in the top bar.
- **The Your robot drawing:** on a car, the size line under the axles no longer runs into the labels of the devices below it.
- **Camera not answering on some Windows laptops:** the console couldn't find a Pi by its `.local` name when Windows only answers the name for IPv4 or IPv6 asked separately, so the camera showed "isn't answering" while the Pi was up. It now looks up each separately.
- **An open page no longer saves old controls back.** A console page kept its own copy of the controls and only refreshed it on load, so after the controls changed elsewhere (another tab, Practice, the API), the next edit there, even moving the speed slider, saved the old copy over them. With mirrored drive motors, that could make them fight. The page now takes changes made elsewhere, unless an edit of its own is still being saved.

## [0.8.0] - 2026-11-27

### Added
- **A footer** on every page: the version, a link to the source on GitHub and to fiodar.ai, the licence status (all rights reserved for now; three.js MIT, YOLOX Apache-2.0) and that LEGO and Sony's trademarks aren't ours.
- **Controls follow the motors:** when a port your controls use has no motor, but every job can find one, the console moves the jobs onto the motors that are plugged in (steering to a medium motor, driving to the large ones) and keeps each job's settings. It waits for the motors to stay the same for 1.5 s and for nobody to have driven for 2 s, never moves anything with a motor missing, and says what moved on the Robot page.
- **Wrong-port warning:** a motor plugged into a sensor port (1–4), or a sensor in a motor port (A–D), is marked **Wrong port?** on the brick on the Robot page, and the note above it says which ports to check. The brick can't identify a motor in a sensor port, so a sensor port that stays unidentified for 3 seconds is flagged.
- **Drive gearing** under **Robot size** on the Map page: **Motor turns per wheel turn**, for robots with gears or a differential between the drive motors and the wheels. The map, the speed shown, the obstacle brake and the top speed calibration use it. It starts at 1, so robots set up before keep working as they did.
- **Handbrake:** hold ◯ on the controller (F on the keyboard) and the motors that drive brake, while steering still works. The throttle keeps going underneath, so letting go powers straight out of the slide. For drifting with grip-reduced rear wheels.
- **Robot weight** under **Robot size** on the Map page, in grams. Saved with the robot's size, for planning later; nothing uses it yet.
- **Car calibration,** repeatable, on the Driving page: **Find steering limits** (feels for both end stops, sets centre, keeps the steering 4° inside them), **Measure left/right turn** (drives a slow circle at full lock; gives the turning circle, the wheels' real angle and the map's steering ratio), and **Top speed**, learned while driving straight at full power and shown for the battery voltage now. Kept in `pc/calibration.json`.
- **Practice brick:** a medium steering motor on D, with end stops at 55° each way, starting a little off centre.
- **Bigger recognition models, and the graphics chip:** choose Fast (nano), Balanced (tiny), Better (s) or Best (m) under **Recognition model** on the Map page, and whether it runs on the processor or the graphics chip.
  - **Downloads:** `python pc/tools/get_model.py --all` (or `--model s`), each checked against a pinned checksum. All four are YOLOX, Apache-2.0.
  - **The graphics chip** needs `onnxruntime-directml` instead of `onnxruntime`. With two graphics chips, the console times each and uses the faster.
  - **The camera view and the Map page** say which model runs, where, and how long a picture takes.
- **Motor groups:** a port can be **Same as** another port, so two motors (two large motors on one axle, say) run as one. The follower gets exactly the leader's command, optionally reversed. Set it from **Works with** on each motor in the Robot page's Devices list, or on the Driving page. Testing either motor moves the whole group, and the brake and the map count both as driving.
- **Sensor names in the Devices list:** EV3 sensors show as "Colour sensor", "Infrared sensor" and so on, as the brick program asks each one what it is, instead of "EV3 sensor".
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
  - **Quick to connect by name:** the console tries the Pi's IPv4 address first. On Windows, a `.local` name otherwise cost about 2 seconds per connection, on a refused IPv6 attempt.
  - **Setup guide:** `docs/CAMERA.md`.
  - **3D Raspberry Pi** in the Camera setup panel, shown as a Pi 2 or Pi 3: what plugs in where.
    - The camera ribbon, with its contacts facing the HDMI port.
    - The camera module, power, the microSD card underneath, the WiFi dongle or built-in WiFi, and the lights.
    - Numbered markers on the model match a list that explains each connection. Pointing at a list entry lights up its part, and parts turn green when the camera is live.
    - It shows a Pi 3 B+ (built-in WiFi under a metal cover, PoE header) or a Pi 2 (USB WiFi dongle).
  - **Camera setup is three short steps:**
    1. Prepare the SD card: a model switch, three facts and a one-line "Which one do I have?".
    2. Plug everything in: the 3D Pi, with part buttons and one explanation at a time.
    3. Start the camera and connect: the command with a Copy button, then the address and key.
    - Each step turns green as it is done.
  - **Full screen:** the Camera view goes full screen with a button, F or a double-click, and driving keeps working there. A small overlay shows whether the motors are on.
  - **Own window:** a button opens just the video in a separate window (`/camera`), e.g. for a second monitor. Clicking into it takes the focus from the console, which switches the motors off; click back in the console to drive.
- **Controller colour swatches** replace the colour dropdown on the Robot page.
- **Object recognition** on the camera's video, run on the laptop (optional):
  - **What it shows:** boxes and names for 80 kinds of everyday thing (people, cups, bottles, chairs, balls, pets…), about 10 times a second.
  - **Turning it on:** the **Recognise objects** button on the Camera view, or **R**, also in full screen. It runs only while it's on screen, and stops a few seconds after you leave.
  - **Setup:**
    - PowerShock's first optional packages: `numpy`, `onnxruntime`, `pillow`, in `pc/requirements-vision.txt`.
    - The YOLOX-nano model (Apache-2.0, 3.7 MB), downloaded by `pc/tools/get_model.py`, which checks its SHA-256 checksum.
    - Without them the console works as before, and the page shows the setup commands.
  - **Guide:** `docs/VISION.md`.
  - **Tests:** decoding the model's output, overlapping boxes, the frame reader, the checked download, and starting and stopping. Tests that need the packages are skipped without them.
  - **Fresh pictures only:** each start waits for a new picture, never one left from an earlier run, which could be from another camera.
- **Obstacle brake,** on the laptop: with an infrared or ultrasonic sensor facing ahead, the robot slows down near obstacles and stops short of them.
  - **Settings:** on the Driving page, on by default. It slows from 40 cm and stops 15 cm short.
  - **Only driving towards the obstacle is braked:** backing away and turning on the spot always work.
  - **Allows for delay:** it allows for how far the robot has driven since the sensor reading (up to a quarter of a second old), using the speeds the brick measures.
  - **No reading for 0.8 s:** it stops driving towards whatever might be there.
  - **Speed comes back gradually** after a stop.
  - **Shown while braking:** in the status bar, the camera's full-screen view and on the Map page.
  - **Robot side:** no brick upload is needed. It only ever takes speed away from the commands.
- **Things the camera recognises on the map:** labelled markers where they stand, kept as the robot drives on.
  - **Distance:** worked out from the camera's height and tilt (new **Robot size** fields), or from the infrared sensor straight ahead.
  - **Turning it on:** **Recognise things while this page is open** on the Map page.
- **The map** draws the brake's stop and slow-down lines in front of the robot.
- **The camera watches the floor** (`pc/floor.py`, needs only Pillow): in about 30 directions, how far the floor is free before something stands on it.
  - **For the brake:** the nearest thing across the robot's whole width counts, not just along the infrared sensor's line. **Use the camera too** on the Driving page, on by default.
  - **On the map:** a green fan of free floor and a red edge where things stand, marked on the map like the infrared sensor's finds.
  - **In Practice,** a pretend camera sees the practice room.
- **More room for people and pets:** with object recognition set up, a person, cat, dog or bird close ahead makes the brake keep twice the distance, at half the speed.
- **The camera on the 3D robot,** with lines to the corners of the floor it can see, so its height and tilt can be checked by eye.
- **Moving between WiFi networks,** for driving from floor to floor:
  - **The brick** keeps every network added under **Set up WiFi** (adding one no longer replaces the others), and **Forget** removes one. Only their names are ever read back.
  - **Brick program:** when the signal is weak, it moves to the strongest saved network or access point. It only looks while the robot stands still, at most every two minutes, and only with two or more saved networks, because a scan stalls the link for a second or two. It sends its signal in the status line (`w=-62`).
  - **The Pi:** a new service, `pi/powershock_wifi.py`, does the same with NetworkManager, and the camera reports its signal.
  - **The console** finds the brick again if it comes back at a new address.
  - **Adding a network over WiFi** works too: the brick saves it and restarts its WiFi a moment later, and the console reconnects. It used to need Bluetooth.
  - **The map's instrument panel** shows both signals.
- **An instrument panel on the map:** live speed, heading and turn rate, an arrow showing where the robot will be in a second, and what the autopilot (the obstacle brake, for now) decides: what you ask for against what it allows, why, and its last few decisions.
- **Where the camera sits, worked out:** stopping at a few distances from a box, the infrared sensor and the camera together suggest the camera's tilt and height. **Use these** on the Map page saves them.

### Fixed
- **A switched-off brick no longer looks connected:** the brick's screen says NOT REACHABLE, each port "Not available", the Devices list says why, and the top bar says "Brick not reachable" instead of "Brick found". The console forgets its last port check once the brick stops answering.
- **The console stopping** shows on the page (the brick's screen, the message strip, the Devices list) instead of freezing on the last live picture. Status requests time out and never pile up.
- **The Map** no longer shows the last sensor readings, beam and speed once the brick stops sending.
- **The Setup page's** Pairing steps, Change network, Enter address and camera Set up buttons work again, and so does **Calibrate** for the sticks.
- **PowerShock running but not connected** shows as ready on the brick's screen, not "not running". The WiFi tile says "last seen" for an address remembered from before, and Upload waits until the brick answers.
- **Obstacle brake with two range sensors:** with infrared and ultrasonic both plugged in, the brake followed only the sensor on the later port, even when the other saw something nearer. It now goes by whichever sees the nearer obstacle.
- **Motors that share a shaft no longer strain against each other while stopped,** which made the batteries hot. leJOS keeps a stopped motor actively holding its angle, and two motors on one shaft each held a different angle, so they stalled against each other with the robot standing still (about 1.8 A, falling voltage). A stopped speed motor now brakes at once, then floats after 0.3 s. Steering still holds its angle.
- **Sensors on the real brick:** the brick program now asks each EV3 sensor what it is. Under leJOS, the brick's port detection never says which EV3 sensor is plugged in, so on a real brick no sensor was ever read (the practice brick hid this).
- **Saving the robot size** on the Map page showed "Saved." on the Driving page instead.

### Changed
- **Notices sit in a strip right under the top bar,** across the whole width, instead of a card on each page. What the controller needs (a button press, waking up) is the tooltip of its amber icon in the top bar, with its battery.
- **Stop looks inactive** (grey) while nothing can move: Motors off, no motor turning, no calibration drive. It still works then (click, Space or Esc), and turns red the moment anything can move.
- **The Devices list** (test each motor, which motors work together) moved into the **Your robot** card, under the drawing; with the brick out of reach it hides instead of repeating that.
- **The Gearing page's 3D gears** look like LEGO's: gears from 20 teeth have a full-width toothed rim, a thinner web with the holes in it and a raised hub round the axle, in slightly glossy plastic; the double-bevel gears are black.
- **The 3D brick** shows the WiFi dongle (a USB stick with a blue light) and the SD card when the brick reports them, and now faces you with that side. On smaller screens the 3D brick, controller and Pi take a fifth less room.
- **The 3D controller's labels** sit next to the stick or button they describe, with a thin line to it, and follow the model as you turn it; on narrow screens they stay in a row below.
- **Car and Tank** are picked with small top-view drawings; the Robot tab has a robot icon.
- **Your robot,** a new card on the Robot page: the car (or tank) from above, drawn to its saved sizes, with each motor, sensor and the camera where it sits, wired to its port on the brick and coloured by how it's doing. Below it: weight, wheels and gearing, size, top speed, turning circle and steering. **Car / Tank / Fit to my motors** and the robot's sizes moved here from the Driving and Map pages; replacing your own controls with a plain layout now asks first. The Robot tab has a car icon.
- **Driving page:** no Normal speed slider (it's the Motors slider in the top bar).
- **Controller colour** is one swatch: each click moves on to the next colour.
- **A Pi page** for the Raspberry Pi camera: its status, the setup steps and the object recognition model (moved from Setup and the Map page).
- **Setup repeats itself less:** with the brick not answering it says so once, and the brick's files, programs, ports and details wait until it answers. The file and program lists fold under "Files and programs on the brick".
- **Robot page:** the camera has its own card next to the brick (no more Brick/Camera tabs), and with no picture it's a short message instead of a black box. The 3D controller card moved to the **Controller** page. Notices (what to do next, the controller needing a button press) share one slim panel at the top of every page. F only goes full screen while the controller drives, since it's the keyboard's handbrake.
- **Motors is a slider in the top bar:** all the way left is off; anywhere else is on, at that speed limit (the Driving page's Normal speed). The motor test buttons use the same speed, so the Devices card no longer has its own Speed buttons.
- **A strip under the top bar** says what to do next, or what's wrong, on every page, in plain words instead of the SSH error. The top bar shows icons and coloured dots, with the words in each item's tooltip, so Stop always fits.
- **Motor groups on the Driving page** share one card: the leader's settings, with each motor that follows it (and its Reversed switch) underneath.
- **Motors on is in the top bar,** next to Stop, on every page. The controller in the top bar opens a **Drive with** menu (Controller or Keyboard), which also says how the controller is doing. The Robot page card now only appears when there's something to say: the controller needs a button press, or the keyboard's keys.
- **A new look: an instrument cluster at night,** and the old look kept as **Day look**:
  - **Cabin and panels:** a dark blue-graphite cabin, with panels drawn as hairline edges rather than shadows.
  - **Lit wells:** the 3D brick, controller, gears, Pi, map and camera sit in lit wells.
  - **Light shows state:** selected items are backlit, and live things glow in the EV3's status-light colours (green, amber, red).
  - **Stop motors:** the button glows red while the motors are on. It stays still if you've asked your system for less motion.
  - **Headings and readouts** use Bahnschrift, the DIN lettering of road signs and dashboards, built into Windows.
  - **The map** draws the infrared beam as light at night, and walls it's sure of grow brighter.
  - **Switching looks:** **Day look** at the bottom of the menu switches, and the choice is remembered.
- **A simpler menu: 6 pages instead of 8,** with nothing removed:
  - **Setup** brings together Connection, Program and Brick, in the order you use them: Connect (Bluetooth, WiFi, Practice, Camera), Program on the brick, Brick. Status bar items jump to their section, and old links (`#connection`, `#program`, `#brick`) still work.
  - **Controls is now Driving**, so it isn't confused with Controller.
  - **Gearing** moved to the end of the menu, below a divider, as a tool.
  - **Opening a page** starts at its top, instead of at the last page's scroll position.
  - **The Devices list** on the Robot page links to the specs for each port.
  - **A Start button that can't be used** now looks greyed out, not green.
  - **README screenshots** show the new menu.
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

### Security
- **Motors can't stay on across a dropped link,** even one that comes straight back between two status checks: the console numbers each link and refuses input switched on for an earlier one, and forgets the last input when the link drops. Motors can't be switched on without a link.

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

[Unreleased]: https://github.com/fryzhykau/lego-ev3-powershock/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/fryzhykau/lego-ev3-powershock/releases/tag/v0.8.0
[0.7.0]: https://github.com/fryzhykau/lego-ev3-powershock/releases/tag/v0.7.0
