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

## 1. Prepare the SD card

1. **Install the OS:** on the laptop, install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and choose **Raspberry Pi OS Lite**. Use the 32-bit version for a Pi 2.
2. **Before writing,** open the settings (**Edit settings**) and set:
   - a host name, e.g. `ev3cam`
   - a user name and password of your own
   - your WiFi network and country
   - **Enable SSH**, under Services
3. **Write the card.** Put it in the Pi.

## 2. Connect the camera

The console's **Connection → Camera → Set up** panel shows all of this on a 3D Raspberry Pi. Pick Pi 2 or Pi 3, and point at an entry in the list to see where it goes.

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

1. Open **Connection → Camera → Set up**.
2. Enter the Pi's address (`ev3cam.local`, or its IP address), port `8080` and the access key.
3. Click **Save and test**. The tile shows **live** and the picture size.
4. On the **Robot** page, switch the 3D view to **Camera**.

The video only runs while the Camera view is on screen.

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
