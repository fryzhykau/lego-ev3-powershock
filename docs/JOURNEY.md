# How PowerShock came about

This is a log of how the project grew: the ideas, the order they came in, and what worked and what didn't along the way. It's written for anyone building something similar, and for us, so the same mistakes aren't made twice.

The project was built in a few long sessions over two days (25–26 November 2026) by the owner and Claude Code. The owner brought the ideas, the hardware and the testing, and Claude wrote the code. For what changed in each version, see [CHANGELOG.md](../CHANGELOG.md). For problems and their fixes, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## The short version

| Stage | Idea | Result |
|---|---|---|
| 0 | DualShock 4 talks straight to the EV3 over Bluetooth | Designed, never got to run. Kept as experimental "variant B" |
| 1 | Go through the laptop instead | ✅ The main path, and it works |
| 2 | Get the laptop and brick talking | ✅ After batteries, a hidden-network bug and a few legacy settings |
| 3 | See what's plugged into the brick, live, in 3D | ✅ Works, including hot-plugging motors |
| 4 | Choose which stick drives which motor | ✅ Tank, Car, "Fit to my motors", steering centre |
| 5 | Make the controller part feel finished | ✅ Pairing, battery and firmware, calibration, sleep help |
| 6 | 3D models that look like the real things | ⚠️ Took four attempts; worked once built from reference drawings |
| 7 | Clean up every page | ✅ Repeated passes, driven by "too much at once" feedback |
| 8 | Make it safe before driving and before going public | ✅ Motors stop on every kind of failure; console locked down |
| 9 | Publish it | ✅ Public repo, versioning, changelog, privacy check, agent rules |
| 10 | A Tesla-style map of the room from the sensors | ✅ Works in Practice mode; not yet tried on the real robot |
| 11 | Let the robot see through a camera | 🔄 Software ready and tested; the Pi is being set up |
| – | Control cheap RC toy cars too | 💡 Options worked out, nothing built |

## Stage 0: the first idea, a direct Bluetooth driver

**Idea:** drive the EV3's motors from a PS4 DualShock 4 with no computer in between. The controller would talk Bluetooth straight to the brick, which runs leJOS (Java).

**What was designed** (in an earlier claude.ai chat):
- **A DualShock driver written for leJOS:** it opens the controller's Bluetooth channels itself (L2CAP, through JNA calls into Linux), switches the controller into full reports, and reads the sticks and buttons.
- **The fallbacks considered:** a USB cable into the brick, the ev3dev firmware, or relaying through a PC.

**What happened:**
- **None of that code was ever compiled.** It had no leJOS environment and no brick to run on. The code itself was lost: Claude Code can't read claude.ai chats, so only an exported summary survived. (A feature request was filed for that.)
- **The risks the chat already named were real:**
  - many controllers refuse a connection from a host they aren't paired with
  - the leJOS Bluetooth service may hold the channels
  - the controller must be put in pairing mode (Share + PS) every time
- **Outcome:** rebuilt from the summary, it now exists as `powershock-bt.jar` ("variant B"). It compiles and can be uploaded, but it's still untested with a real controller.

**Lesson:** the most elegant path (no computer) was also the riskiest. Starting with the boring path got a robot moving on day one.

## Stage 1: the pivot, through the laptop

**Idea:** let Windows handle the controller, which it already does well, and send motor commands to the brick over the network.

**What worked:**
- **On the brick:** a small receiver (`DS4Receiver`) listens on TCP port 5000. If nothing arrives for 500 ms, the motors stop.
- **On the laptop:** a local web console (`pc/ev3_console.py`, Python standard library only). The browser reads the DualShock through the Gamepad API, and the console sends commands 50 times a second.
- **The first prototype** was a pygame client (`pc/ds4_client.py`). The web console replaced it within hours, because a page could show much more: ports, battery, 3D views.

**Lesson:** a local web page turned out to be the right "app". No installs, it's easy to redesign, and it can show everything at once.

## Stage 2: getting the laptop and the brick to talk

This took longer than any feature. What went wrong, in order:

| Problem | What it turned out to be | Fix |
|---|---|---|
| The leJOS WiFi menu said "No access points" | The dongle was fine (WNA1100, solid blue light) and a scan over SSH found 16 networks. The menu trips over nearby hidden networks | Join WiFi from the console over Bluetooth instead: it writes the WiFi settings with a hashed key |
| The brick switched off when Bluetooth pairing started | Batteries at about 6 V | Fresh batteries (about 8–9 V); the console now warns below 7.5 V |
| Paired, but no network | Windows 11 needs *Devices and Printers → right-click EV3 → Connect using → Access point*; the old shell folder shows empty | Steps built into the Connection page |
| SSH refused to connect | leJOS has a 2008 SSH server (dropbear 0.51) | Legacy algorithm options, and an empty password supplied by script |
| Modern JDK can't build for the brick's Java 7 | JDK 20+ dropped Java 7 targets | Compile against the brick's own Java 7 library as Java 8, then patch the class version |
| "Run program" over the menu's remote interface was sometimes ignored | It seemed to fail while the menu sat in a sub-screen | Start programs with `jrun` over SSH |

**What worked in the end:** both Bluetooth (the brick at `10.0.1.1`) and WiFi.

**Lesson:** check the battery first, and when a menu says something odd, look underneath it (SSH) before believing it.

## Stage 3: seeing the brick live

**Idea:** show what is plugged into each port, in real time, on a 3D brick.

**What worked:**
- **Reading the ports:** the EV3's kernel keeps a "what's plugged in" table for every port. leJOS reads it through hidden (protected) methods, and a small subclass (`PortWatch`) reads them cheaply. The brick streams all 8 ports and the battery 4 times a second.
- **Motor hubs:** they turn on screen with the real motor angles.
- **Hot-plugging:** a motor plugged in while the program runs starts working within a quarter of a second.

**What didn't, at first:**
- A port that a program has open reads as "nothing" while the program has it.
- A program that was killed instead of closed left its ports unreadable even after it exited. The fix: wake detection up at start, release ports on exit, and only claim a motor port once a motor is seen there.

## Stage 4: controls

**Idea:** any stick to any motor, for any robot.

**What worked:**
- **Port modes:** each port can be two-wheel drive, speed, a steering angle, or off.
- **Starting points:** **Tank** or **Car** presets, plus **Fit to my motors**, which guesses from what's plugged in.
- **Steering ports** get a **Centre** control: nudge the wheels straight, then set it as zero.
- **Motor tests:** test each motor from the page, by holding a button or turning exactly 90° or 360°.

**Lesson:** sending raw stick values and doing the mapping on the laptop kept the brick program simple, and made settings changes instant.

## Stage 5: the controller

**What worked:**
- **Controller details:** battery, model and firmware are read straight from Windows' HID API (no installs).
- **Calibration:** **Calibrate** learns each stick's rest position and range; a dead zone and response curve follow.
- **Help where it's needed:** pairing steps that tick themselves off, and clear help when the controller falls asleep ("press PS").

**What didn't, at first:**
- **The controller didn't appear right after pairing.** Browsers hide controllers until a button is pressed while the page is open (a privacy rule), so the page now says so.
- **The browser's own way to read the battery (WebHID) showed no device picker** inside the app's browser. That's why the console reads the controller from Windows instead.
- **The first calibration didn't save:** it rejected any stick movement during the "rest" step. It now has a short countdown and restarts the step if a stick moves.
- **Firmware updates:** whether the controller's firmware was the latest couldn't be checked. Sony only updates DualShock 4 firmware through a PS4 or PS5.

## Stage 6: 3D models

This is where the most iterations went:

| Attempt | Approach | Verdict |
|---|---|---|
| 1 | Flat 2D drawing | "Looks pretty flat" |
| 2 | Extruded outline plus tube-shaped grips | "Dual handles", "proportions are off" |
| 3 | Tweaked sizes and positions from memory | "You still have not improved it" |
| 4 | **Traced from a measured layout drawing and photos** (Wikimedia Commons): one smooth shell from a distance function, grips that flow out of the body | ✅ Matches the real controller |

The EV3 brick went the same way. It was right only after comparing against a photo: raised grey screen housing, seam line, white sides, grey band. The gears needed a redraw to remove artifacts.

**Lessons:**
- **Start from a reference** (a dimensioned drawing, a photo), not from memory.
- **Compare side by side** before calling it done.
- **Check the screenshot method too:** headless browser screenshots flattened the CSS 3D brick until software 3D rendering was switched on, so screenshots can be misleading.

## Stage 7: layout, again and again

Every page was reworked at least once, mostly prompted by one of these:
- "why are these separate cards?"
- "the Stop button is weird and unclear"
- "the reset view button doesn't need to be that big"
- "these icons can be confused with each other"
- "information overload"

**Principles that came out of it:**
- **Setup behind buttons:** setup steps go behind a button, not in always-open cards.
- **One explanation at a time:** show it where it's needed, with details behind a link or on hover.
- **Say what's happening:** a Stop button labelled "Stop motors", red when motors are live, with its keyboard key shown.
- **Small controls:** colour swatches instead of a dropdown, and icons instead of big buttons.
- **Status that's honest:** "Not answering" with the last-seen time, instead of a stale "Connected".

The Program page layout and folding the Brick page into the others are still waiting.

## Stage 8: safety and security

**Before driving:**
- **The motors stop:** within 0.5 s of silence, at once on a dropped link, and when the controller disconnects or the page loses focus.
- **No surprise restarts:** after a dropped link, **Motors on** switches itself off, so the robot never drives off by itself when the link comes back.
- **A Stop can't be undone** by a late message.
- **Connections:** only one connection to the brick at a time, and old commands are dropped instead of piling up.

**Before going public**, a security review:
- **The console:** it answers only its own page, checks where requests come from, needs its own header on every request, and caps request sizes.
- **The brick program:** range limits, input size caps, and a separate thread for status so a stuck connection can't block the safety stop.

**Lesson:** the review found real bugs a user would hit while driving: a "Not used" motor that kept spinning, and the steering jumping when a setting was saved. That review was worth more than any feature.

## Stage 9: publishing

**What was set up:**
- **Versioning:** one version for the whole app (`VERSION`), a changelog, and the brick program reporting its version to the console.
- **README** with screenshots, all taken in Practice mode. The brick's Bluetooth address was blanked out of one.
- **Rules for coding agents:** `AGENTS.md`, plus `CLAUDE.md` for Claude Code, so Codex and Claude follow the same rules: privacy, safety, tests, Java 7 limits.
- **Privacy check:** `pc/tools/privacy_check.py` runs with the tests and blocks addresses, network names, keys and SD-card files from being committed.
- **Commit email:** commits use a GitHub no-reply address.

Still open: choosing a licence.

## Stage 10: a map of the room

**Idea:** like a car's autopilot display, build a 3D picture of the surroundings from the EV3's own sensors while driving.

**Feasibility first:**
- the infrared sensor sees about 70 cm, with a wide beam
- the ultrasonic sensor sees about 1.5 m
- the colour sensor only sees the floor right under it
- position comes from the wheels (it drifts), helped by a gyro if one is plugged in

**What was built:**
- **On the brick:** a sensor thread reads IR, ultrasonic, colour and gyro sensors.
- **On the laptop:**
  - works out where the robot is
  - keeps a grid of what was seen, with a score per cell, so one stray reading doesn't draw a wall
  - paints floor colours
- **In Practice mode:** the pretend robot drives around a small room with two boxes, blue tape and a red mat, so the map can be tried without hardware.

**What didn't, at first:**
- the map blocks were invisible: three.js culled them by the bounds it measured at the start
- the camera animated in from the start point instead of starting at the robot
- the walls of the first practice room were out of the IR sensor's range

**Status:** works in Practice mode. The real robot needs the new brick program uploaded.

## Stage 11: giving the robot eyes

**Starting point:** what was at home.
- a Raspberry Pi 3 Model B+
- a Pi camera module with a screw-in lens
- a Sony Action Cam

**The choice:** the Pi and its camera ride on the robot and stream over WiFi. The Sony camera's WiFi live view would force the laptop onto the camera's own network, and an EV3 webcam would be tiny and slow.

**What was built and tested with a test pattern:**
- **Pi streamer:** `pi/powershock_cam.py`, standard library only, works with any Raspberry Pi OS camera tool, and needs an access key for every request.
- **Console:** relays the video, so the page only ever talks to the console.
- **Robot page:** a Brick | Camera switch, full screen, and an own-window mode for a second monitor.
- **Setup guide:** a 3D Raspberry Pi showing what plugs in where, in three short setup steps.

**Things learned along the way:**
- **Which Pi it was:** the clue was the name printed on the board. The WiFi dongle that was plugged in suggested a Pi 2, but it's a 3 B+ with WiFi built in.
- **A separate camera window and safety:** clicking into it takes the focus from the console, which switches the motors off. So driving stays in the console window, and full screen happens inside the console.
- **The first setup panel was "information overload":** a full table, a notes list and seven paragraphs. It became three steps with one explanation at a time.

**Status:** the Pi's SD card is being prepared: Raspberry Pi OS Lite 64-bit on a 128 GB card.

## Side ideas

- **Cheap RC toy cars:** three ways were worked out. Wire a small board across the toy remote's buttons; replace the car's receiver with an ESP32; or copy the 2.4 GHz signal with a radio module. Nothing built yet.
- **Sony Action Cam:** kept as a fallback camera.
- **Reading old claude.ai chats from Claude Code:** not possible today, so a feature request was filed.

## What worked and what didn't, overall

**Worked:**
- **The simple path first:** going through the laptop instead of the clever direct Bluetooth driver.
- **A local web console** instead of a desktop app.
- **Practice mode:** a pretend brick (now with a pretend room). It made almost everything testable without hardware.
- **Lots of small passes** on each page, each one driven by the owner's own reactions.
- **Reference drawings and photos** for anything that has to look real.
- **A separate review** for safety and security before going public.
- **Writing down every change to the brick** with how to undo it (kept in a private device log).

**Didn't work, or took several tries:**
- **Building 3D models from memory.**
- **Trusting what menus and browsers said:** the WiFi menu's "No access points", the missing WebHID picker, the flat headless screenshots.
- **First versions of anything with steps:** calibration, setup panels. They needed a second design once someone actually used them.
- **Putting everything on screen at once.**

## Open threads

- **Upload the new brick program** (0.8, with sensors) and try the map on the real robot.
- **Finish the Raspberry Pi setup** and drive with the camera.
- **Choose a licence.**
- **Program page layout,** and folding the Brick page into the other pages.
- **Release 0.8.0** once the map and camera are tested on hardware.
