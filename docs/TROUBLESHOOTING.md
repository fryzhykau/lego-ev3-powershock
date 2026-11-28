# Troubleshooting a leJOS EV3 from Windows

Things we ran into getting a leJOS 0.9.1-beta brick talking to a Windows 11 laptop. The console app (`pc/ev3_console.py`) handles most of these for you.

## Battery

- The leJOS screen shows the battery voltage in the top-left corner. **When the number blinks, the battery is low.**
- At about **6.1 V** the brick switched itself off the moment Bluetooth pairing started. A USB WiFi dongle also draws a lot of power.
- Fresh AA alkalines read about 8.5–9 V. The console shows the live voltage and warns below 7.5 V.

## WiFi: "No access points" in the leJOS Wifi menu

- leJOS 0.9.1 supports the **Netgear WNA1100** (Atheros AR9271, `ath9k_htc`). Other "N150" Netgear dongles use Realtek chips that leJOS has no driver for. A solid blue light on the WNA1100 means the driver loaded.
- The dongle only does **2.4 GHz**. Plug it in **before** turning the brick on.
- Even with a working dongle, the leJOS menu showed "No access points" while a scan over SSH (`wpa_cli -i wlan0 scan_results`) found 16 networks. The menu apparently trips over nearby **hidden networks** (empty names) or unusual security flags.
- **Workaround:** connect over Bluetooth first, then use the console's *Put the brick on WiFi*. It scans from the brick, writes `/home/root/lejos/config/wpa_supplicant.conf` with a hashed key (the password itself never reaches the brick), and runs leJOS's own `startwlan`.
- A router that shows **WPA3** to the laptop may still offer WPA2 to older devices (WPA2/WPA3 mixed mode); the brick's scan shows `WPA2-PSK` in that case. WPA3-only networks won't work.

## Bluetooth network (PAN) on Windows 11

1. On the brick: Bluetooth menu, **Visibility on**. The default PIN is `1234`.
2. Windows: Settings, Bluetooth & devices, Add device, **EV3**.
3. Pairing alone doesn't give a network. Open **Devices and Printers** (`shell:::{A8A91A66-3A7D-4424-8D24-04E180695C7A}`), right-click **EV3**, then **Connect using → Access point**.
   - The older "Bluetooth Devices" shell folder (`{28803F59-…}`) shows as empty on Windows 11; don't use it.
4. The brick is then `10.0.1.1` and the laptop gets `10.0.1.x` from it.

## SSH into the brick

leJOS runs **dropbear 0.51** (2008): user `root`, empty password, and only legacy algorithms.

```powershell
ssh -o KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o Ciphers=+aes128-cbc root@10.0.1.1
```

- OpenSSH 10 has dropped `ssh-dss`, so only `ssh-rsa` can be re-enabled. The brick offers an RSA host key, so that's enough.
- Press Enter at the password prompt. For scripts, `pc/ev3_brick.py` supplies the empty password through `SSH_ASKPASS`.
- Copy files with `ssh ... "cat > /home/lejos/programs/x.jar" < x.jar`. The brick's scp is unreliable.

## Starting programs remotely

- The leJOS menu exposes an RMI interface on port 1099 (`//10.0.1.1/RemoteMenu`, `lejos.remote.ev3.RMIMenu`): run and stop programs, list programs, versions, and `configureWifi`. `//10.0.1.1/RemoteEV3` gives battery voltage and current. See `pc/tools/BrickMenu.java`.
- `runProgram` was sometimes ignored, apparently while the menu sat in a sub-screen. The console falls back to `jrun -jar` over SSH.

## Building for the brick with a modern JDK

- The brick runs **Java 7** (`ejre1.7.0_60`). JDK 20 and newer can't target Java 7.
- `build.ps1` compiles against the brick's own Java 7 class library (`lib/rt7.jar`, taken from your SD card), using `-source 8 -target 8`, then lowers the class-file version from 52 to 51. That's safe when the code uses no lambdas or other Java 8 features.
- Jar manifests need `Class-Path: /home/root/lejos/lib/ev3classes.jar /home/root/lejos/libjna/usr/share/java/jna.jar`.

## Port detection

- `lejos.hardware.device.DeviceIdentifier` reports what's plugged into each port (`OUTPUT_TACHO:TACHO` large motor, `OUTPUT_TACHO:MINITACHO` medium motor, `UART:COL-REFLECT` colour sensor, and so on). `PortProbe.java` wraps it.
- Ports that a running program has open fail with `DeviceException`, and the console shows them as "in use".

## Live port detection (what's plugged in, in real time)

- The EV3 kernel's connection manager (DCM) keeps a connection type and device type for every port in shared memory. leJOS reads them with `protected static` methods on `lejos.internal.ev3.EV3AnalogPort` (`getPortType`, `getMotorPortType`, `getMotorType`, `getAnalogSensorType`). A subclass can call them; see `ev3/src/powershock/PortWatch.java`. Reading them is cheap, so the receiver streams all 8 ports to the PC 4 times a second.
- Codes: connection 125 = tacho motor, 122 = EV3 UART sensor, 121 = EV3 analog (touch), 126 = nothing. Device type 7 = large motor, 8 = medium motor, 16 = touch, 29 = colour, 30 = ultrasonic, 32 = gyro, 33 = infrared.
- **A port that a program opens reads 0:0**, because detection is switched off while it's in use. **A program that was killed rather than closed leaves its ports reading 0:0 even after it exits.** Opening a port as a `ConfigurationPort` switches detection back on (`PortWatch.prime()`), and the receiver now closes its motors in a shutdown hook.
- So the receiver only claims a motor port once a motor is detected there. Unused ports stay free and keep detecting, so a motor plugged in later shows up and starts working within a quarter of a second.
- A cable with nothing on the other end reads as an empty port.
- **A motor in a sensor port** was seen reading 127:127 (connection error): the sensor ports can't identify a motor. The motor ports A–D then read 126 (nothing) and nothing drives. Motors go in the lettered ports above the screen, sensors in the numbered ports below the buttons. The console marks a sensor port that reads like this for 3 seconds, or a motor port with something other than a motor in it, as **Wrong port?** on the Robot page. An EV3 sensor that's just been plugged in can read 127 for a second or two while it starts, which is why it waits.
- With busybox `ps` the command line is cut short; find processes by `/proc/<pid>/cmdline` instead.

## Motors

- Once opened, a motor reports its position (`getTachoCount`, degrees), speed (`getRotationSpeed`, degrees/s) and `isStalled()`. The receiver includes these in its status line, and the console turns each 3D motor hub to the real position.
- There's no electronic spec sheet: the brick only knows large vs medium (device type 7 / 8). The console shows LEGO's published figures by type.

## DualShock 4 battery, model and firmware

- The browser's Gamepad API only gives buttons and axes. Chrome and Edge can read more through **WebHID** (`navigator.hid.requestDevice({filters: [{vendorId: 0x054c}]})`, with one user OK per controller).
- Product IDs: `054C:05C4` = DS4 first version (CUH-ZCT1), `054C:09CC` = second version (CUH-ZCT2).
- Battery: input report `0x01` over USB, byte 29 of the data (`0x11` over Bluetooth, byte 31). The low 4 bits are the level (0–10 on battery, 0–11 on cable, 11 = full); bit 4 means a cable is plugged in.
- Over Bluetooth the controller sends a short report without the battery until feature report `0x02` (calibration) is read; reading it switches it to the full report.
- Feature report `0xA3` holds the firmware build date/time and hardware/firmware version numbers.
- The DS4 doesn't report Bluetooth signal strength. Sony updates DS4 firmware only through a PS4/PS5; there's no Windows updater (the PC updater is for the DualSense).

## The obstacle brake

- **The robot won't drive forward:** something is closer than the stop distance (15 cm by default), or the sensor reads something that isn't there. The status bar says "Stopped" with the distance. Back away if coverage allows, or turn a tank on the spot.
- **"No reading":** the brick stopped sending sensor readings for 0.8 s. The link is probably about to drop: check WiFi.
- **"No usable reading ahead" or "behind":** **Brake coverage required** is on. Check the range sensor faces the direction you want to drive, or check the camera is sending a clear floor view for forward driving. A tank can still turn on the spot. If asked for a layout, select **Car** or **Tank** on the Driving page.
- **It doesn't brake:**
  - The infrared or ultrasonic sensor must face straight ahead or straight back. Set which way under **Edit sizes and where things sit** (Your robot, on the Robot page). A sensor facing sideways isn't used for braking.
  - The brake needs a driving layout on the Driving page (two-wheel drive, or speed ports on the throttle).
  - Upload the latest brick program: versions before 0.8 don't send sensor readings.
- **It stops too late:** make **Slow from** larger, or lower **Normal speed**. The infrared sensor only reads up to about 70 cm, and misses thin chair legs.
- **It stops too early:** the infrared sensor's distance depends on the colour of what it sees. Dark things read further away, light things nearer. Lower **Stop short by**.

## Motors stay off after Stop

- Turn **Motors** on again after Stop, a link drop, loss of page focus, or a controller that goes quiet. Motor tests and steering calibration also need Motors on. Choose **Keyboard** in the top bar if you have no controller connected.
- Practice settings last until the console closes. After changing back to the brick, the console shows the brick's own controls, sizes and calibration. To carry over just the controls, speed and brake settings, use **Copy Practice controls to brick profile** in Setup while Practice is on.

## Things on the map from the camera

- **Markers are in the wrong place:** set the camera's height, tilt and view angle under **Edit sizes and where things sit** (Your robot, on the Robot page). Distance comes from where things meet the floor in the picture, so a wrong height or tilt moves everything.
- **Nothing appears:** a thing must be seen twice, at least 50% sure. Things seen against the sky or above the horizon (on a shelf high up) aren't placed.

## Hot batteries, or a high current while standing still

- **The cause seen on this robot:** two large motors on one shaft. Before the fix, each held the angle it had stopped at, and they strained against each other without end. Upload the latest brick program: stopped motors now float.
- **Something powered from the brick:** a Raspberry Pi in the brick's USB port draws far more than the brick is made for. Give the Pi its own power bank.
- **What to do:** switch the brick off (take the batteries out if it doesn't respond), let hot batteries cool before charging, and throw away any that look swollen or leak.

## Moving between WiFi networks

- **It doesn't switch:**
  - The brick only looks for a better network while it stands still, only when its signal is below -60 dBm, at most every two minutes, and only with two or more networks saved. The Pi looks whenever the signal is below -60 dBm.
  - Only saved networks are used. On the brick, add each network under **Set up WiFi**. On the Pi, use `sudo nmcli --ask device wifi connect <name>`.
  - The brick's WiFi dongle only sees 2.4 GHz networks.
  - Upload brick program 0.8 or later.
- **The link keeps dropping for a few seconds:** check the brick's signal on the live map (Driving page). Below about -70 dBm, the EV3's WiFi dongle loses many packets (ping the brick to see), and the console treats 1.5 s without news from the brick as a lost link. Move the dongle where the robot's motors and brick don't shield it (a short USB extension helps), or add a closer 2.4 GHz network.
- **The link drops for a few seconds on a switch:** that's normal. The motors stop (the brick's 0.5 s safety stop), and the console connects again. Drive on once **Motors on** is back on.
- **The console doesn't find the brick after a switch:** the laptop must be on the same home network. A second router (not an extender or mesh) makes a separate network, which the laptop can't reach. Put it in access point mode (its settings may call it "AP mode" or "bridge mode"), so all the floors share one network.
- **The Pi's switching:** `journalctl -u powershock-wifi` says what it did and why.

## The camera and the floor

- **"Watching the floor needs Pillow":** run `python -m pip install pillow` (or the whole `pc/requirements-vision.txt`).
- **"The floor is too patterned to judge":** a rug or tiles with strong patterns. The brake then uses only the infrared sensor. Nothing to fix; on a plainer floor it comes back by itself.
- **The robot stops for nothing:**
  - A line on the floor (tape, a rug's edge, a strong shadow edge) looks like something standing there.
  - The robot itself is in the picture: point the camera up a little, so the bottom of the picture is floor.
  - Switch off **Use the camera too** on the Driving page to brake with the sensor only.
- **The free floor on the map is too short or too long:** set the camera's height and tilt under **Robot size**, or let the map work them out (see the README's Map section).
- **The worked-out height is missing:** it needs stops both near (about 20 cm) and further away (50 cm or more).

## Object recognition on the camera

- **"Needs a one-time setup":** install the packages and get the model, as the page shows. The full steps are in [VISION.md](VISION.md).
- **`pip` can't find `onnxruntime`:** it needs 64-bit Python 3.10 or newer.
- **"The model file isn't the one PowerShock expects":** the download was damaged or is another version. Run `python pc/tools/get_model.py` again; it checks the SHA-256 checksum before keeping a file.
- **No boxes:** the model knows 80 everyday kinds of thing (the COCO set), not LEGO parts, walls or doors. It needs a sharp, well-lit picture; fast turns blur it.
- **"Too many camera views are open":** recognition uses one of the console's three video connections to the Pi. Close the camera's own window or another console tab.
