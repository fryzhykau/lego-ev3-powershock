# The robot's camera

A Raspberry Pi with a camera rides on the robot and sends live video over WiFi. The PowerShock console shows it on the Robot page: switch the 3D view from **Brick** to **Camera**.

```
Pi camera ─ribbon─▶ Raspberry Pi ──WiFi──▶ laptop (console) ──▶ browser
                    pi/powershock_cam.py     relays the video
```

The EV3 program doesn't change: the console still drives the motors, and the camera is just another source the console reads.

## You need

- **A Raspberry Pi:** Pi 2, 3, 4 or Zero 2 W. A Pi 2 has no WiFi of its own, so it needs a supported USB WiFi dongle.
- **A Raspberry Pi camera module:** the original 5 MP (OV5647), the v2 (IMX219) or a compatible one. Night-vision modules with a screw-in lens work too.
- **A microSD card,** 8 GB or more.
- **A USB power bank** with a short cable, to power the Pi on the robot. Get one that can supply at least 2 A for a Pi 2, or 2.5 A for a Pi 3.
- **Something to mount it:** zip ties, or LEGO Technic beams. The Pi's mounting holes take M2.5 screws.

## Which Raspberry Pi do I have?

The name is printed on the board in small white letters, usually between the GPIO pins and the processor. Unclip the top of the case if it's hard to read.

| Look for | Pi 2 B | Pi 3 B | Pi 3 B+ |
|---|---|---|---|
| Processor (big square chip in the middle) | black | black | shiny silver lid |
| Small silver cover with the Raspberry Pi logo (the WiFi) | – | – | yes |
| Little 4-pin header next to the end of the GPIO row | – | – | yes |
| Tiny chip antenna by the display connector | – | yes | – |
| Built-in WiFi and Bluetooth | no | yes (2.4 GHz) | yes (2.4 and 5 GHz) |
| Power supply | 5 V, 2 A | 5 V, 2.5 A | 5 V, 2.5 A |
| In Raspberry Pi Imager | Raspberry Pi 2, OS Lite 32-bit | Raspberry Pi 3, OS Lite 64-bit | Raspberry Pi 3, OS Lite 64-bit |

- **Pi 3 B and B+:** WiFi is built in, so no USB WiFi dongle is needed.
- **Once it's running,** `cat /proc/device-tree/model` prints the exact name.

The console's Camera setup shows the same notes for the model you pick.

## 1. Prepare the SD card

1. **Install the OS:** on the laptop, install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) Choose your Pi model, then **Raspberry Pi OS Lite**: 64-bit for a Pi 3, 32-bit for a Pi 2.
2. **Before writing,** open the settings (**Edit settings**) and set:
   - a host name, e.g. `ev3cam`
   - a user name and password of your own
   - your WiFi network and country
   - **Enable SSH**, under Services
3. **Write the card.** Put it in the Pi.

## 2. Connect the camera

The console's **Pi** page shows all of this on a 3D Raspberry Pi. Pick Pi 2 or Pi 3, and point at an entry in the list to see where it goes.

With the Pi unplugged:

1. **Pi end:** gently lift the clip of the **CAMERA** connector. On a Pi 2 or 3 it sits between the HDMI port and the audio jack. Slide the ribbon in with its **metal contacts facing the HDMI port**, then press the clip down.
2. **Camera end:** the contacts face the camera's circuit board.
3. **Extra lead:** a small 2-wire lead on night-vision modules is for IR lights or a day/night filter. You can leave it as it is.

## 3. Check the camera

Power the Pi and wait a minute. Then, from PowerShell on the laptop:

```powershell
ssh <your user>@ev3cam.local
```

On the Pi:

```sh
rpicam-hello --list-cameras      # Raspberry Pi OS Bookworm or later
libcamera-hello --list-cameras   # Bullseye
```

**If no camera is listed** but it's plugged in, it's often a third-party module that the Pi doesn't detect by itself. Add these two lines to `/boot/firmware/config.txt` (on Bullseye: `/boot/config.txt`), then reboot:

```
camera_auto_detect=0
dtoverlay=ov5647
```

Use `dtoverlay=imx219` instead for a v2 camera.

## 4. Copy and start the streamer

From PowerShell on the laptop, in the PowerShock folder:

```powershell
scp pi\powershock_cam.py <your user>@ev3cam.local:
```

On the Pi:

```sh
python3 powershock_cam.py
```

It prints a line with the **access key**. Every request to the camera needs that key, so others on your network can't watch. The key is kept in `~/.powershock-cam-key`.

Options:

- `--flip`: the camera is mounted upside down.
- `--width 480 --height 360 --fps 15`: smaller and smoother over weak WiFi. The default is 640 × 480 at 20 frames a second.
- `--port 8080`: the default port.

It works with whichever camera tool the OS has: `rpicam-vid`, `libcamera-vid`, or `raspivid` on older systems. Nothing needs installing.

## 5. Connect the console

1. Open the **Pi** page; **Camera setup** is below the camera.
2. Enter the Pi's address (`ev3cam.local`, or its IP address), port `8080` and the access key.
3. Click **Save and test**. The tile shows **live** and the picture size.
4. On the **Robot** page, switch the 3D view to **Camera**.

The video only runs while the Camera view is on screen.

To have the laptop recognise things in the video (people, cups, balls, pets…), see [VISION.md](VISION.md).

## 6. Start it with the Pi (optional)

So you don't need SSH every time, make it a service. Create `/etc/systemd/system/powershock-cam.service` with `sudo nano`:

```ini
[Unit]
Description=PowerShock camera
After=network-online.target
Wants=network-online.target

[Service]
User=<your user>
ExecStart=/usr/bin/python3 /home/<your user>/powershock_cam.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:

```sh
sudo systemctl enable --now powershock-cam
```

## 7. Move to the strongest WiFi (optional)

The Pi only changes WiFi network when the one it's on is lost altogether. If the robot drives between floors, each with its own router or extender, it clings to the far one, and the video gets choppy. `pi/powershock_wifi.py` fixes that. Every 5 seconds it looks at the signal. When the signal is weak (below -60 dBm) and a saved network is at least 8 dB stronger, it switches. After a switch it stays at least a minute, so it never flaps between two.

1. **Save every network** the robot drives through on the Pi, typing each password yourself when asked:

   ```sh
   sudo nmcli --ask device wifi connect <network name>
   ```

   This joins the network straight away, so run it last for the one you want to stay on now. `sudo nmtui` does the same with menus.
2. **Try it** (it only says what it would do):

   ```sh
   sudo python3 powershock_wifi.py --dry-run --once
   ```

3. **Make it a service**, like the camera. Copy `pi/powershock_wifi.py` to the Pi, and create `/etc/systemd/system/powershock-wifi.service` with `sudo nano`. It runs as root, because looking for networks and switching need it:

   ```ini
   [Unit]
   Description=PowerShock WiFi: move to the strongest saved network
   After=NetworkManager.service

   [Service]
   ExecStart=/usr/bin/python3 /home/<your user>/powershock_wifi.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   ```sh
   sudo systemctl enable --now powershock-wifi
   journalctl -u powershock-wifi -f    # watch it switch
   ```

To undo: `sudo systemctl disable --now powershock-wifi`, then delete the service file.

**The Map page** shows the camera's signal next to the brick's, so you can see where in the house it gets weak.

## Trying it without a Pi

On the laptop, with Pillow installed (`pip install pillow`):

```powershell
python pi\powershock_cam.py --test
```

This shows a moving test pattern. Enter `127.0.0.1` as the address in the console.

## Notes

- **Delay:** typically 0.2–0.4 s on good WiFi. If the picture stutters, lower the size or frame rate, or move closer to the router.
- **Privacy:**
  - The video travels unencrypted on your local network, protected by your WiFi password and the access key.
  - Use it on networks you trust.
  - The console stores the camera's address and key in `pc/camera.json`, which git ignores. Never commit it.
