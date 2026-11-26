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
