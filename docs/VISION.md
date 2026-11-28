# Object recognition

The console can recognise everyday things in the robot camera's video: people, cups, bottles, chairs, balls, pets and about 70 more. It draws a box and a name around each one, live, while you drive.

![Object recognition on the Camera view, with a test picture: a red disc the model takes for a frisbee](screenshots/vision.png)

```
Pi camera ──WiFi──▶ console on the laptop ──▶ browser: video
                      │
                      └─ pc/vision.py: newest frame ──▶ model (YOLOX-nano) ──▶ boxes and names ──▶ browser
```

- **Where it runs:** on the laptop, not the Pi. A Pi 3 manages 2–4 pictures a second, while a laptop manages 10, with time to spare.
- **What it costs:** recognition runs only while the Camera view is on screen with recognition turned on, and stops a few seconds after you leave. It uses two CPU threads at most, so driving stays smooth.
- **Privacy:** everything stays on the laptop. Nothing is uploaded, and the only internet access is the one-time model download.
- **Safety:** recognition only shows what it sees. It never moves the motors.

## You need

| | What | Why |
|---|---|---|
| Python | **3.10 or newer** | onnxruntime has no packages for 3.9 |
| Packages | `numpy`, `onnxruntime`, `pillow` (in [`pc/requirements-vision.txt`](../pc/requirements-vision.txt)) | numbers, running the model, reading JPEG pictures |
| Model | `pc/models/yolox_nano.onnx`, 3.7 MB | the trained network that recognises things |
| Camera | the Raspberry Pi camera from [CAMERA.md](CAMERA.md), working in the console | the pictures to look at |

This is the only part of PowerShock that needs anything beyond the Python standard library. Without it, everything else works as before.

## Set it up (once)

In PowerShell, in the PowerShock folder:

1. **Install the packages** (about 30 MB to download):
   ```powershell
   python -m pip install -r pc\requirements-vision.txt
   ```
2. **Get the model:**
   ```powershell
   python pc\tools\get_model.py
   ```
   It downloads `yolox_nano.onnx` from the official YOLOX releases on GitHub and checks its SHA-256 checksum before keeping it. A changed or broken download is refused and deleted.
3. **Check it:**
   ```powershell
   python pc\tools\get_model.py --check
   ```
   It should say `yolox_nano.onnx is there and its checksum is right.`

There's no need to restart the console: it notices the packages and the model the next time you turn recognition on.

## Bigger models, and the graphics chip

Four sizes of the same model can be chosen under **Recognition model** on the Pi page. Bigger ones find smaller and farther things, and guess wrong less often, but take longer per picture.

| Choice | Model | Download | Looks at | Accuracy (COCO mAP) | Processor | Graphics chip |
|---|---|---|---|---|---|---|
| Fast | nano | 3.7 MB | 416 × 416 | 25.8 | 13 ms | 3 ms |
| Balanced | tiny | 20 MB | 416 × 416 | 32.8 | 39 ms | 15 ms |
| Better | s | 36 MB | 640 × 640 | 40.5 | 157 ms | 14 ms |
| Best | m | 101 MB | 640 × 640 | 46.9 | 392 ms | 18 ms |

The times are for the model alone, measured on one laptop (Intel Core i9-13900H; NVIDIA RTX 4070 Laptop GPU). Recognition runs at most 10 times a second, so anything under about 80 ms a picture keeps up; on the processor, **Balanced** is the largest that does.

1. **Get the other sizes:**
   ```powershell
   python pc\tools\get_model.py --all
   ```
   Or one at a time: `--model tiny`, `--model s`, `--model m`. Each is checked against its own pinned checksum.
2. **Use the graphics chip** (optional). Swap the processor-only package for the DirectML one, which works with any DirectX 12 graphics chip on Windows (NVIDIA, AMD or Intel) and needs no NVIDIA CUDA toolkit:
   ```powershell
   python -m pip uninstall -y onnxruntime
   python -m pip install onnxruntime-directml
   ```
   To go back: uninstall `onnxruntime-directml` and install `onnxruntime` again.
3. **Choose** on the Pi page: the model, and **Runs on**. "Graphics chip if there is one" uses it when the DirectML package is installed. A laptop often has two graphics chips (one built into the processor); the console times each when a model loads and uses the faster one.

The camera view and the Pi page say which model is running, where, and how long each picture takes. The choice is kept in `pc/vision.json` (git-ignored).

## Use it

1. Open the **Robot** page and switch the 3D view to **Camera**.
2. Click the **Recognise objects** button (the square in a frame, next to full screen), or press **R**.
3. Boxes and names appear on the video. The line at the bottom says how many times a second it's recognising, and what it sees.

Click the button or press **R** again to turn it off. The console remembers your choice. **R** also works in full screen.

## On the map

What's recognised can also go on the live map (Driving page), as labelled markers where things stand. Turn on **Recognise things while the Driving page is open**, next to the map. Recognition in the Camera card on the Robot page puts things on the map too.

- **Direction** comes from where the thing is across the picture. **Camera sees across** under **Robot size** is the camera's view angle: 62° for the Pi camera v2, 54° for v1, more for a wide lens.
- **Distance** comes from where the bottom of its box meets the floor. That needs the camera's **height** and how far it **looks down**, also under **Robot size**. Straight ahead, the infrared sensor's distance is used instead.
- **Accuracy:** a few centimetres close up, tens of centimetres at 2–3 m. Things whose bottom is cut off by the picture's edge are placed at the nearest floor the camera can see. Things further than 4 m aren't placed.
- **Wrong guesses:** a thing has to be seen twice before it's drawn. One that should be in view but isn't seen for about 1.5 seconds is taken off.
- **Things on a table** are placed as if they stood on the floor behind it, as the picture can't tell the difference.

## The floor, without the model

The console also uses the camera's pictures to see where the floor is free (`pc/floor.py`). That needs only Pillow, not numpy, onnxruntime or the model. It runs while the console is linked to the robot and **Use the camera too** is on (Driving page), and feeds the obstacle brake and the map. See [Map](../README.md#map) in the README.

- **How:** it shrinks each picture to 64 × 48, learns what the floor just in front of the robot looks like, and follows 32 columns upwards until they stop looking like floor. Colour and brightness are compared apart, so a shadow is still floor.
- **Speed:** about 2 ms a picture, up to 10 a second.
- **With recognition set up,** it recognises at the same time, so the brake can give people and pets more room.

## What to expect

- **What it knows:** 80 kinds of thing, from the COCO set: people, animals (cat, dog, bird, horse…), vehicles, furniture (chair, sofa, table, bed), kitchen things (cup, bottle, bowl, fork…), electronics (TV, laptop, phone, keyboard), and toys and sport (ball, teddy bear, kite…). It doesn't know LEGO bricks, walls or doors.
- **How sure it is:** only things it's at least 40% sure of are shown, with the percentage.
- **Speed:** about 15 ms a picture on a typical laptop, capped at 10 pictures a second.
- **Delay:** each box comes from a picture 0.1–0.3 s old, so it trails slightly behind fast movement.
- **Small and far things** are found less often: the model looks at the picture at 416 × 416.
- **Blur:** fast turning blurs the picture, and blurred things aren't recognised. Drive slower, or add light.

## Where things are

| File | What it is | In git? |
|---|---|---|
| `pc/vision.py` | reads frames from the camera, runs the model, keeps the newest result | yes |
| `pc/worldmap.py` | places what's recognised on the map (`WorldMap.see`), and the free floor (`WorldMap.surround`) | yes |
| `pc/floor.py` | finds where the floor ends in each direction; Pillow only | yes |
| `pc/tools/get_model.py` | downloads and checks the model | yes |
| `pc/requirements-vision.txt` | the three packages | yes |
| `pc/models/yolox_*.onnx` | the models | **no**: `pc/models/` is ignored |
| `pc/vision.json` | which model, and where it runs | **no**: your own choice |

Each model's address, size and checksum are fixed in `pc/vision.py` (`MODELS`).

## The model and its licence

- **Models:** [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) nano, tiny, s and m, by Megvii, trained on the COCO dataset. All four come from the same YOLOX release (0.1.1rc0).
- **Licence:** Apache-2.0, for all four.
- **Why they aren't in this repository:** they're binary files with their own licence, so each person downloads them from their source.
- **Checksums (SHA-256):**
  - nano: `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d`
  - tiny: `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7`
  - s: `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`
  - m: `21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f`

**Without the tool:**

1. Download `yolox_nano.onnx` yourself, from the YOLOX GitHub releases (version 0.1.1rc0).
2. Put it in `pc\models\`.
3. Run `python pc\tools\get_model.py --check`. A file with a different checksum isn't used.

## When something's wrong

| What you see | What to do |
|---|---|
| "Object recognition needs a one-time setup on this laptop" | Run the two setup commands above. The message lists only what's missing. |
| `pip` can't find `onnxruntime` | Your Python is too old, or 32-bit. Install 64-bit Python 3.10 or newer from python.org, then install the packages again. |
| "The model file isn't the one PowerShock expects" | The file is damaged or a different version. Run `python pc\tools\get_model.py` again. |
| `get_model.py` says it couldn't get the model | Check the internet connection. A company network may block GitHub downloads; then download it by hand as above. |
| "isn't downloaded yet" when choosing a model | Run `python pc\tools\get_model.py --model <name>` (or `--all`). |
| **Runs on** says processor although you chose the graphics chip | The DirectML package isn't installed, or no graphics chip could run the model. See "Bigger models, and the graphics chip". |
| "Too many camera views are open" | Close the camera's own window, or another console tab: recognition needs one of the 3 video connections. |
| Boxes are missing or flicker | The picture is blurred or dark, or the thing is small or far away. Slow down, add light, or move closer. |
| Driving feels slow while recognising | Unlikely, as it's capped at 10 a second and 2 threads. If it happens, close other heavy programs, or turn recognition off while driving. |

## Removing it

1. Delete the `pc\models` folder.
2. Optionally, uninstall the packages:
   ```powershell
   python -m pip uninstall onnxruntime
   ```
   numpy and Pillow are often used by other programs, so keep them unless you know they aren't.
