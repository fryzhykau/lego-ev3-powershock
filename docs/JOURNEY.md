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
| 11 | Let the robot see through a camera | ✅ Live video from the Pi in the console; not yet mounted on the robot |
| 12 | Recognise things in the video, on the laptop | ✅ Works on the real camera; not yet tried while driving |
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

**A fresh look at the menu (after the camera worked):** eight pages had grown one at a time.
- **Three thin pages became one:** Connection (four tiles), Program (three buttons and two lists) and Brick were all about getting the brick ready, and were visited in that order. They became **Setup**, with three sections: Connect, Program on the brick, Brick.
- **Two names were too close:** "Controls" and "Controller" were easy to mix up. Controls became **Driving** ("which stick drives which motor").
- **Tools apart from driving:** Gearing moved below a divider at the end of the menu.
- **Nothing removed:** old addresses (`#connection`, `#program`, `#brick`, `#controls`) still open the right place, and the status bar jumps to the right section.

What didn't, at first:
- **A missing bracket** in the merge script stopped the whole page. A syntax check of the page's script now runs before trying it in the browser.
- **Scroll position:** one long Setup page meant other pages opened half-way down, as each page kept the last scroll position. A new page now opens at its top.
- **Private details in screenshots:** the new Setup screenshot showed the brick's Bluetooth address and the camera's host name. Both were replaced with placeholders, found by their pixels.

**A new look: "an instrument cluster at night."** The owner asked for something that feels supernatural and modern.
- **The idea:** a driving console should look like a car's dashboard after dark.
  - **Light shows state:** unlit is idle, backlit is selected, glowing is live.
  - **Status colours:** taken from the EV3's own status light.
  - **The one bold move:** the 3D models and the camera sit in lit wells, like a car configurator's turntable.
  - **Type:** Bahnschrift, Windows' built-in DIN, so nothing needs downloading.
- **What made it cheap:**
  - **Colour tokens:** most colours already went through about a dozen of them, so a new look was mostly new values.
  - **Transparent canvases:** the 3D views draw on them, so their backdrops are plain CSS.
  - **The old look stayed** as **Day look**.
- **What broke, and was caught by looking:**
  - **Invisible text:** "strong fill plus white text" was hard-coded in many places, and the strong fill turned light at night. The brick's port labels and other text vanished.
  - **The map:** walls drawn darker the surer they were disappeared on a dark floor. The red beam became a muddy blob, so at night it's drawn as light.
  - **Swatches:** dark controller colour swatches vanished on dark panels.
  - **The screenshot redaction** assumed dark text on white. It now samples the tile's own colour.

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

**Status:**
- **The Pi is running:** Raspberry Pi OS Lite 64-bit on a 128 GB card, set up in Imager with WiFi and SSH. It answered on the network about 100 seconds after its first boot.
- **The camera is live in the console:** 640 × 480 at 20 frames a second, with the Pi only about 10% busy.
  - **The camera (OV5647):** detected without any `config.txt` change.
  - **SSH:** the laptop's key was added once with the Pi's password, typed by the owner. Since then it logs in without one.
  - **The access key:** the owner pasted it into the console, so it never went through the agent.
- **A surprise:** every connection to the Pi took 2.1 s. The `.local` name also gives an IPv6 address, the streamer listens on IPv4 only, and Windows retries a refused connection for about 2 s before moving on. The console now tries IPv4 first.
- **The picture is pinkish** indoors: a night-vision camera with its infrared filter open.
- **Learned on the way:** the Pi has no BIOS to update (its firmware is on the SD card and updates with the system), and no gyro (the EV3 gyro sensor does that job).

## Stage 12: recognising things in the video

**Idea:** run object recognition on the camera's video while the robot moves.

**Where to run it:**

| Option | Speed | Verdict |
|---|---|---|
| On the Pi 3 B+ (TensorFlow Lite) | 2–4 pictures a second | Too slow, and it heats and drains the Pi |
| On the Pi with a Coral USB stick | 15–25 a second | Extra hardware to buy |
| **On the laptop**, from the video the console already relays | ~15 ms a picture, capped at 10 a second | ✅ Chosen |

**What was built:**
- **`pc/vision.py`:** reads the Pi's video, keeps only the newest frame so it never falls behind, and runs YOLOX-nano (3.7 MB, 80 kinds of thing).
- **On the page:** boxes and names over the Camera view, a status line, and a button or **R** to turn it on and off.
- **Only when wanted:** it runs only while the Camera view shows it, and stops a few seconds after the page stops asking.
- **Setup:** a guide (`docs/VISION.md`) and a download tool that checks the model's checksum.

**Decisions:**
- **The first dependencies:** the owner agreed to PowerShock's first packages outside the standard library (numpy, onnxruntime, Pillow), kept optional: without them everything else works, and the page shows the setup commands.
- **The model stays out of the repository:** each person downloads it from its source, checked against a fixed checksum.
- **Choosing the model:** the popular newest YOLO versions are AGPL-licensed, so the Apache-2.0 YOLOX was picked.

**What didn't, at first:**
- **A loose size limit:** the download's size cap had slack, which the test for "too big" caught.
- **A misleading screenshot:** with a moving test picture, each box trailed behind its object (it belongs to a frame about 0.1 s old). The screenshot uses a still picture, and the guide explains the delay.

- **A stale first result:** on the real camera, the first "find" was the stand-in camera's last picture, still in memory from the test before. Each start now waits for a fresh picture.

**Status:** runs on the real Pi camera, 10 times a second at about 16 ms a picture. Not yet tried while driving.

## Stage 13: an obstacle brake, and the map learns what things are

**Idea:** the first step towards self-driving. The robot slows down and stops by itself for what's in front of it. At the same time, the 3D map shows what the camera recognises, where it stands, as the car drives.

**Where the brake runs:** the first plan was the brick, so it would react without WiFi. The owner chose the laptop instead: one place for all the logic, nothing to upload, and the laptop already sees both the sensors and the camera.
- **The cost:** the sensor reading is up to a quarter of a second old by the time it's used.
- **The answer:** the brake works out how far the robot has driven since, and brakes for where the obstacle is now.
- **The brick's own 0.5 s safety stop** is still there underneath.

**What was built:**
- **`pc/brake.py`:** sits after the controls mapping in the 50-a-second loop, and only ever takes speed away.
  - **Slows** from 40 cm and **stops** 15 cm short.
  - **Only motion towards the obstacle** is braked. For a tank, only the forward part of the command is cut, so turning on the spot still works.
- **Recognised things on the map** (`WorldMap.see`):
  - **Direction** from the box's place across the picture.
  - **Distance** from where its bottom edge meets the floor, given the camera's height and tilt, or from the infrared sensor when it's straight ahead.
  - **Kept honest:** seen twice before it's drawn, and dropped when it should be in view and isn't.
- **A test that drives:** the practice robot drives at the box ahead at full speed, and must stop 12–22 cm short.

**What didn't, at first:**
- **Creeping:** the speed went down smoothly towards zero but never got there. The robot crawled the last few centimetres at 1–2 % speed, which a real motor still turns at. Below 10 % it now stops, and once stopped it waits for a clear margin before starting again, so it doesn't shuffle.
- **Panic braking:** speed was first worked out from when the sensor lines *arrived*. When two lines arrived together, the robot seemed to have leapt forward, and the brake stopped it 10 cm early. The brick already measures each motor's speed, so that is used instead.
- **A test that measured the wrong thing:** its distance check used the map's position, which misses the first quarter second after **Clear map**. It now reads the sensor itself.
- **A line drawn backwards:** the stop line first appeared behind the robot, because of an angle check that tested the wrong way round.

**Status:** works in Practice. Not yet tried on the real robot, whose infrared readings are noisier and depend on the colour of what's ahead.

## Stage 14: the camera sees the floor, and where it sits

**Idea:** the infrared sensor sees one narrow line. To avoid a chair leg off to one side, the robot needs to know how far it's clear in every direction. And the map only works out distances from the camera right if it knows where the camera sits on the robot.

**What was built:**
- **Free floor** (`pc/floor.py`): learn what the floor in front of the robot looks like, then follow each of 32 columns of a small picture upwards until it stops looking like floor. That row, with the camera's height and tilt, is a distance.
  - **Colour apart from brightness:** red and green as shares of the brightness, so a shadow is still floor.
  - **The floor is remembered:** a box filling the bottom of the picture isn't learned as the new floor.
  - **No numpy:** a 64 × 48 picture in plain Python takes about 2 ms.
- **Into the map and the brake:** each direction marks the map at half the infrared sensor's weight. The nearest thing within the robot's width goes to the brake, and the nearer of the camera and the sensor counts.
- **People and pets:** recognition already places them on the map; one close ahead now doubles the brake's distances and halves the speed.
- **A pretend camera for Practice:** the practice room drawn column by column from the robot's true position. With it, a test drives the practice robot at the box with its infrared sensor turned sideways, and the camera alone stops it.
- **Where the camera sits:** while the robot stands still facing a box, the infrared sensor says how far away it is, and the camera says which row of the picture its bottom edge is on. A few of these at different distances pin down the tilt and the height: try every height, take the best average tilt for each, and keep the height where the readings agree best.
- **On the 3D map:** the camera on a mast, lines to the corners of the floor it can see, a green fan of free floor and a red edge where things stand.

**What didn't, at first:**
- **A name used twice** in the 3D map's update function stopped the whole map from loading. The browser console showed it at once.
- **The camera brakes a little early while moving:** its pictures are taken to be 0.15 s old, as a real camera's are. The pretend camera's aren't, so in Practice it stops a few centimetres sooner than needed. On the real robot that allowance is right.
- **Placement from far readings only** gets the tilt right but the height rough: from 36–66 cm the practice camera came out 13 cm high instead of 15. Nearer stops fix that.

**The instrument panel:** a panel over the 3D map shows speed, heading and the autopilot's decisions as they happen. The brake keeps its own short log, and only logs what changes the driving. Merely seeing a box while backing away from it isn't a decision. A decision must also hold for 0.3 s, so driving along the edge of the slow-down zone doesn't fill the log. Stops are logged at once.

**Status:** works in Practice. The real floor, lighting and rugs will decide how well it works at home.

## Stage 15: from floor to floor on WiFi

**Idea:** test the car on more than one floor, each with its own router or extender. The brick and the Pi should each move to whichever network is strongest.

**The problem:** WiFi clients change network only once the current one is lost altogether. Until then, the robot clings to a far router while a near one is in reach, and the link gets choppy long before it breaks.

**What was built:**
- **One rule, in two places:** at -60 dBm or better, stay. Below that, switch only to something at least 8 dB stronger, then stay at least a minute, so it never flaps.
  - **On the brick:** a thread in the brick program, `WifiRoam.java`, with `wpa_cli`.
  - **On the Pi:** a service, `powershock_wifi.py`, with `nmcli`.
  - **Other access points** of the same network count too, so a mesh or an extender with the same name works.
- **Looking around stalls the radio:** a scan takes the brick's radio off its channel for a moment, long enough to trip the motors' 0.5 s watchdog. So the brick only scans while it stands still, or when the signal is so weak the link is failing anyway.
- **Several saved networks on the brick:** adding a network used to replace the one before. Now the console reads the config, swaps in the one network, and writes it back. Their keys never leave that function, and only names are ever shown.
- **A new address:** after a switch, the brick may get a new address. The console looks for the PowerShock program on its networks, checks its "V" greeting, and connects. It only does this when exactly one brick answers, so it never picks a stranger's.
- **Signals on the map:** the brick sends its signal in the status line, and the Pi in its status, so the map's panel shows both while driving.

**What we learned about this house:** the router and its extender give addresses from the same router, so they are one network. Addresses should survive a switch, and the laptop can reach the robot on either floor.

**On the real hardware:**
- **A damaged library on the brick:** the new program wouldn't start: leJOS's own `jna.jar` on the SD card was damaged, probably by switching off without shutting down (leJOS mounts the card unchecked). An intact copy sat next to it.
- **Sensors were never read on a real brick:** the sensor code opened sensors by the type the brick's port detection reports. The practice brick reported it, but on a real brick leJOS leaves it unknown. Now the brick asks the sensor its name ("COL-REFLECT", "IR-PROX"…).
- **Scans dropped the link:** a scan every 30 s at a weak signal stalled the radio long enough for the console to drop the link each time. Now it scans at most every two minutes, only while standing still, and only with somewhere else to go.
- **A weak dongle:** at about -70 dBm, a quarter of the pings to the brick were lost, while the router answered every one. On the car, the brick's 2.4 GHz dongle is the weak link; the Pi, on 5 GHz next to it, had -51 dBm.

## Stage 16: two motors, one shaft

**Idea:** the car has two large motors on its rear axle. A motor group makes the second one get exactly the first one's command ("Same as A"), so they run as one.

**What went wrong:** the batteries got hot while the car stood still. The brick reported 1.8 A with every motor at rest, and the voltage fell from 7.6 V to 4.7 V within an hour. leJOS keeps a stopped motor actively holding the angle where it stopped. A had stopped at -11° and B at 28°, on the same shaft: each pushed towards its own angle against the other, a stall that never ended. Testing one motor while the other held made it worse.

**The fix:** a stopped speed motor still brakes at once (the obstacle brake needs that), then floats after 0.3 s. Steering, a single motor, still holds its angle.

**What it taught:** the brick reports total current 4 times a second. Watching it would have caught this in seconds: a high current with nothing moving always means something is wrong.

## Stage 17: bigger eyes on the graphics chip

**Idea:** recognition runs on the laptop, which has far more power than nano needs. Offer bigger models of the same family, and let the graphics chip run them.

**What was built:**
- **Four sizes of YOLOX** (nano, tiny, s, m), all Apache-2.0 from the same release, each pinned by its checksum. Their output has the same shape, so the same decoding works for all four; only the picture size (416 or 640) differs, and the model says which.
- **DirectML** instead of the processor-only onnxruntime: one package, no NVIDIA CUDA toolkit, and it works with any DirectX 12 graphics chip.
- **Choosing the right chip:** DirectML numbers the chips but doesn't name them. On this laptop chip 0 is the graphics built into the processor and chip 1 the RTX 4070. The console times each when a model loads and keeps the faster.

**Measured (model alone):** nano 13 ms on the processor, 3 ms on the RTX; m, the biggest, 392 ms on the processor, 18 ms on the RTX.

**What didn't, at first:**
- **The wrong chip won:** after one warm-up run, the RTX still looked slower than the built-in graphics, because a big chip takes a few runs to set itself up. Three warm-up runs, then five timed, pick it every time.
- **A chip that isn't there** made onnxruntime print a large error before falling back to the processor. The search now stops quietly at the first missing chip.
- **0 ms:** nano on the RTX was so quick that a picture's time rounded to 0, which a test took as "not running".

## Stage 18: measuring the car

**Idea:** before the app can plan a reverse or a three-point turn, it has to know the car: how far the steering really turns, how tight a circle that makes, and how fast the car goes, which changes as the battery drains. Measure each on the car, in a way that can be repeated.

**What was built** (`pc/calibrate.py`, the Car calibration card):
- **Steering limits:** the steering motor runs gently each way until its angle stops changing: the end stop. Centre is halfway; the steering range is set 4° short of the stops.
- **Turning circle:** the car drives slowly at full lock while the page keeps asking (Motors on, page open, no Stop), with the obstacle brake still underneath. The owner presses Back where it started. The wheels' distance is the circle; a bicycle model turns that and the axle spacing into the front wheels' angle, and so the steering ratio the map uses.
- **Top speed:** whenever the car drives straight at 95% power or more for over a second, its measured speed and the battery voltage are noted. Speed per volt is the fit through zero, since a motor's top speed is close to proportional to its voltage.
- **The practice brick** got a steering motor with end stops, starting 12° off centre, and its pretend car steers from the true centre. So an uncalibrated practice car drifts, as a real one would.

**What didn't, at first:** the steering check found the steering "hardly moved". It had: but the moment it stopped at an end stop, the controls sent the steering back to centre, so the reading came back as 0. While the steering is being calibrated, the controls now leave that port alone.

**Next:** a planner that uses these numbers to choose between turning forward, reversing, or a multi-point turn.

## Stage 19: a handbrake for drifting

**Idea:** make the car slide round a table. There's no brake on the front wheels, but in a drift the handbrake locks the *rear* wheels, and the rear wheels are driven by the large motors, which can brake hard. So a handbrake is just "drive motors to 0 while a button is held", with steering left alone.

**What was built:** hold ◯ (F on the keyboard) and every drive motor, and every motor following one, is sent 0. The brick brakes it, then lets it roll after 0.3 s (the float that stopped two motors on one shaft fighting). The throttle keeps ramping underneath, so letting go powers straight out of the slide instead of ramping up from nothing. Stop still wins: after a stop, power ramps up from 0 again.

**Also:** less grip at the back helps more than anything in the software: smooth tape on the rear tyres, rubber kept on the front. With slipping wheels, the map's distances run long and the obstacle brake needs a longer stop distance.

**Weight** was added to the robot's size, entered from a kitchen scale. It isn't used yet. Physics says it matters when the motors limit how fast the car can stop or speed up, and for when the driven wheels start to spin, but not for a stop limited by tyre grip.

**Gearing:** the car is a big Technic car body, and its rear wheels are driven through a differential whose 28-tooth ring is turned by a smaller gear, so the wheels turn slower than the motors. The map had assumed the motor turns the wheel directly, so speed and distance would have read too high by that ratio. **Motor turns per wheel turn** fixes it. The easiest way to measure it is to roll the car with the brick off until a wheel turns once and count the motor hub's turns, with no teeth to count.

**Wrong ports:** on the first drive of the car nothing moved. The brick saw nothing in motor ports A–D and three things it couldn't identify in sensor ports 1, 3 and 4: the three motor cables were in the sensor ports. Motor and sensor cables are the same, so it's an easy mistake. The console now flags it from the codes the brick already streams.

After rewiring, the motors were in A, B and C (large, medium, large), while the controls still expected A, B and D. So the controls now move to fit the motors: each job (steering, driving, a follower) moves with its own settings to a motor of the right kind. It only does this when every job finds a motor. With one cable loose it would otherwise put the throttle on the mirrored second motor, and the car would drive backwards. Also seen: the brick's port detection can stop updating, and restarting PowerShock fixed it.

**Negative cases:** with the brick and the Pi switched off, the page still showed devices on the ports, from an SSH check 90 minutes old. A read-only audit of every page for "what does this show when X is gone" found 15 such spots. The worst was a safety gap: the page alone switched Motors off when the link dropped, so a drop and reconnect between two status checks (250 ms apart) left it on, and the car would drive on reconnect. Now the console numbers each link and refuses input switched on for an earlier one. The fix for showing old data was one function on the page that says what is known about the brick right now (live, ready, idle, unreachable, console stopped), which everything else reads.

## Side ideas

- **Cheap RC toy cars:** three ways were worked out. Wire a small board across the toy remote's buttons; replace the car's receiver with an ESP32; or copy the 2.4 GHz signal with a radio module. Nothing built yet.
- **Sony Action Cam:** kept as a fallback camera.
- **Reading old claude.ai chats from Claude Code:** not possible today, so a feature request was filed.

## Challenges

The hardest problems so far, grouped by where they came from.

### Old hardware and software on the brick

| Challenge | Why it was hard | How it was handled |
|---|---|---|
| **leJOS 0.9.1 is from 2015, with Java 7** | Today's JDKs can't build for Java 7; no lambdas or newer APIs | Build against the brick's own Java 7 library, patch the class version, keep the code Java 7-only (enforced by the build) |
| **A 2008 SSH server** | Modern SSH clients refuse its algorithms; `scp` is unreliable | Legacy options re-enabled for the brick only; files copied with `cat` over SSH |
| **WiFi menu bug** | "No access points" while 16 networks were in range | Skip the menu: join WiFi from the console over Bluetooth |
| **Only some WiFi dongles work** | leJOS only has drivers for a few chips (e.g. Netgear WNA1100), and only 2.4 GHz | Documented; the right dongle was already in hand |
| **Port detection switches off** | Ports a program opens read as empty, and stay that way if the program is killed | Wake detection at start, release ports on exit, claim a motor port only once a motor is seen there |
| **Weak batteries** | The brick switched off at about 6 V, mid-pairing | Live voltage in the console, with a warning below 7.5 V |

### Windows, the browser and the controller

| Challenge | Why it was hard | How it was handled |
|---|---|---|
| **Bluetooth network on Windows 11** | The needed menu is hidden in the old *Devices and Printers* | Step-by-step, self-ticking instructions with a button that opens it |
| **The controller is invisible to the page** at first | Browsers hide controllers until a button is pressed while the page is open | The page says "press any button" right where you look |
| **Battery and firmware aren't in the browser's controller API** | The browser's own fix (WebHID) showed no picker in the app's browser | Read the controller through Windows' HID API instead, with no installs |
| **Controller sleeps** | It turns itself off after a while | A clear "asleep, press PS" state and help |
| **Firmware updates** | Sony only updates it through a PS4/PS5 | Shown as information; PowerShock works with any version |

### Making it look real

| Challenge | Why it was hard | How it was handled |
|---|---|---|
| **A believable DualShock 4 in code** | Organic shapes; no model files allowed (licences, size) | One smooth shape built from distance functions and traced from a measured drawing, after three attempts from memory |
| **The EV3 brick's proportions and details** | Easy to get roughly right and still look wrong | Matched against a photo of the real brick |
| **Screenshots lied** | Headless browsers drew the 3D brick flat | Software 3D rendering for screenshots, and checking in a real browser |

### Safety, privacy and trust

| Challenge | Why it was hard | How it was handled |
|---|---|---|
| **A robot must never drive off by itself** | Links drop, pages lose focus, controllers disconnect, messages arrive late | Stops at every layer: brick watchdog, stop on disconnect, motors off after any drop, Stop always wins |
| **Driving with the camera on a second monitor** | Clicking another window takes focus, and focus loss stops the motors | Driving stays in the console; full screen happens inside it; the separate window is for watching |
| **A public repo from a personal setup** | Addresses, network names, the WiFi key, Oracle's Java runtime and SD backups were all in the folder | `.gitignore`, a privacy check that runs with the tests, redacted screenshots, a no-reply commit email |
| **Open ports on the network** | The brick's receiver and the Pi camera listen on the network | Range limits and input caps on the brick; an access key on the camera; advice to use trusted networks |

### Design

| Challenge | Why it was hard | How it was handled |
|---|---|---|
| **Too much on screen** | Every feature wanted its own card and instructions | Setup behind buttons, short steps, one explanation at a time, details on demand |
| **Making status honest** | Easy to show "Connected" when the brick has gone quiet | "Not answering" with the last-seen time, last-known details greyed out |

### Working with an AI agent

| Challenge | Why it was hard | How it was handled |
|---|---|---|
| **The original design chat couldn't be read** | Claude Code can't open claude.ai chats | An exported summary was used to rebuild; a feature request was filed |
| **Long sessions** | The conversation outgrew the agent's memory more than once | Summaries carried the context over; lasting facts live in memory notes, the device log and this journal |
| **The agent mustn't type passwords or approve device pickers** | Some steps (WiFi password, browser device permission, SD card settings) need the owner | The owner does those steps, and the tools are built so they're needed as little as possible |
| **Shell quirks on Windows** | Backslashes and line breaks were silently changed when written through the shell | Edit files directly instead of through shell commands (now a rule in CLAUDE.md) |

### Still ahead

- **Map drift:** position from the wheels drifts with every slip. A gyro, or markers on the walls seen by the camera, could pin it down.
- **Short sensor range:** the IR sensor reaches about 70 cm and the ultrasonic about 1.5 m, so the map fills in slowly.
- **Power and weight on the robot:** the Pi, camera and power bank add roughly 200–300 g and need 2.5 A.
- **Camera delay over WiFi:** expected to be about 0.2–0.4 s; to be measured on the real robot.
- **The direct Bluetooth driver (variant B):** still untested; many controllers may refuse a host they aren't paired with.

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

## Stop, Practice, and brake coverage

- A short delay after Stop only covered requests that arrived within that delay. The console now ends the motor session on Stop and checks each queued command again before sending it to the brick. A fresh arm action starts a new session.
- Practice and the brick used the same saved settings even though they have different motors and geometry. Each now has its own controls, map and calibration. Practice keeps its measurements in memory, and copying controls to the brick takes an explicit action.
- A missing or unusable reading is different from a fresh reading of clear space. The optional coverage setting checks the requested direction before allowing the robot to drive.

## Open threads

- **Upload the new brick program** (0.8, with sensors) and try the map on the real robot.
- **Finish the Raspberry Pi setup** and drive with the camera, with object recognition on.
- **Use what's recognised:** it's on the map, and the brake gives people and pets more room. Next: let the robot turn towards a chosen thing while a button is held.
- **Self-driving around the house** (the end goal: EV3, Pi, camera and power bank on one LEGO car).
  - **Who does what:** eyes on the Pi; braking, recognition, the map and planning on the laptop; and the owner holding a button to let it drive.
  - **First step done:** the obstacle brake, on the laptop (stage 13).
  - **Second step done:** the camera sees free floor in every direction it looks (stage 14).
  - **Next:** steer around things, choosing the clear gap nearest to where it's meant to go (a vector field histogram), then exploring by itself while a button is held.
  - **The alternative weighed:** a BrickPi3 board, so the Pi drives the EV3 motors itself. That's one computer on board, but it means new hardware and a rewrite.
- **Choose a licence.**
- **Release 0.8.0** once the map and camera are tested on hardware.
