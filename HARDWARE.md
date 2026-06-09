# Coralboard hardware reference

Everything in this repo targets the **Synaptics Coralboard** (Astra **SL2619**) with its Sensor HAT
shield and the OV5647 camera. This file documents what was verified on the board so you can reproduce
the demos. Values were queried directly from the board.

## SoC and NPU
- **SoC:** Synaptics Astra **SL2619** (`syna,sl2619`, "Grinn AstraCORAL-2619"). 2x Cortex-A55 @ 2 GHz,
  ~1.9 GB RAM.
- **NPU:** "TORQ" (Coral NPU), `torq f7600000.synpu`. SyNAP runtime **3.0**, SDK `scarthgap_6.12_v2.2.0`.
- **Only the 2 preinstalled SyNAP models are usable.** Custom NPU models cannot be compiled for SL2619
  today (the public SyNAP toolkit has no SL2619 target, and the open Torq compiler output hangs on this
  board's firmware). Design around the two models below.

### NPU model 1 - image classification
```
synap_cli_ic -m /usr/share/synap/models/image_classification/mobilenetv2/npu/model.synap --top 5 img.jpg
```
- MobileNetV2, **1000 ImageNet classes**. Labels in the model dir's `info.json` (`["labels"][class_index]`).
- Output: `{"items":[{"class_index","confidence"}], "success":true}` plus a line
  `Classification time: T ms (pre:P, inf:I, post:O)`. **inf** is the pure NPU compute (~33 ms);
  preprocessing adds ~30 ms. This is the NPU's fast path.

### NPU model 2 - object detection
```
synap_cli_od -m /usr/share/synap/models/object_detection/coco/npu/model.synap img.jpg
```
- **80 COCO classes** with boxes. Labels in its `info.json`. Output: `items[]` with `class_index`,
  `confidence`, `bounding_box{origin{x,y},size{x,y}}` in input pixels (stdout also prints `w = .. h = ..`,
  used to normalize). **Inference ~280-300 ms** (slower than classification).

## Sensor HAT shield + onboard I/O (verified)
- **RGB status LED** via the kernel LED class (`max_brightness = 1`, so each channel is on/off -> 7 colors):
  - `/sys/class/leds/red:status/brightness`   (gpiochip0 line 10, `LED_RED`)
  - `/sys/class/leds/green:status/brightness` (gpiochip0 line 11, `LED_GREEN`)
  - `/sys/class/leds/blue:status/brightness`  (gpiochip3 line 1, `LED_BLUE`)
  - Some channels carry a default trigger (e.g. `red:heartbeat`); write `none` to the channel's
    `trigger` file before writing `brightness`.
- **Buzzer:** `BUZZERn` on **gpiochip0 line 6** (no PWM -> active buzzer). Drive it with `gpioset`
  (libgpiod: `gpioset`/`gpioinfo`/`gpiodetect` are present). See `shared/leds.py` for the exact pulse.
- **User button:** `USER_BUTTONn` (gpiochip5 line 26), exposed as input device "keys".
- **Microphones:** work (card0 `klamath-asoc`, capture; `arecord`). **No speaker** - the buzzer is the
  only audio out. (The demos in this repo don't use the mics, but they are available.)
- **Camera (OV5647, MIPI CSI):** pin the caps to `640x480` and feed `jpegenc` directly - a `videoconvert`
  element breaks the ISP format negotiation. Two ways to capture, both verified:
  - **One-shot** (simple, but cold-starts the sensor -> ~365 ms and dark until AE settles):
    ```
    gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! video/x-raw,width=640,height=480 ! jpegenc ! filesink location=out.jpg
    ```
  - **Continuous** (what `shared/camera.py` uses): a persistent python-gi **appsink** pipeline
    (`v4l2src io-mode=2 ! ... ! jpegenc ! appsink`) keeps the sensor streaming and pulls the latest JPEG
    frame (~9 fps, AE stays settled, frames stay valid). NOTE: this ISP's `multifilesink`/file-stream
    sinks deliver **0 frames** - only `appsink` (or a single `filesink` one-shot) works.
  - Always **release** the pipeline on exit (`camera.release()`); a leaked GStreamer process keeps
    `/dev/video0` open and makes every later capture fail (the same class of wedge as the NPU).
  - Indoor frames look dark: the sensor's auto-exposure meters on bright light sources (a ceiling lamp)
    and underexposes the rest. `shared/camera.py` lifts the shadows with a gamma curve - tune it with
    `CORAL_CAM_GAMMA` (default `0.45`, lower = brighter) and `CORAL_CAM_BRIGHTEN` (default `1.3`); set
    both to `1` to disable. Gamma beats auto-contrast here, which a bright lamp pinning the white point
    defeats. If frames are *absent* (not just dark) after a reboot, re-seat the CSI flex.
- **No Wi-Fi** (M.2 slot empty) -> connectivity is USB networking (see below).

## Board access
- **adb:** headless, root, no password. (`adb shell`, `adb push`.)
- **Internet over USB (macOS):** board `usb0` = 192.168.137.2, Mac gadget iface = 192.168.137.1, upstream
  = your Wi-Fi. Run `./net_board_internet.sh` from the Mac (one command; it configures both sides).
- **Copy this repo to the board:** `./copy_to_board.sh` (uses `git archive` + `adb push`).

## Software stack (no torch)
- **Gemma 3 270M:** GGUF via `llama-cpp-python` using the prebuilt aarch64 CPU wheel (no source compile).
  Runs on the A55 cores. `models/fetch_models.sh` downloads `models/gemma-3-270m-Q8_0.gguf`.
- **Vision:** the NPU (SyNAP CLIs above). No torch, no transformers.
- The local web server is Python stdlib only (`http.server` + Server-Sent Events).

## Gotchas
- `/usr/local/bin` is **read-only**.
- `/tmp` is a small tmpfs (RAM). Point `TMPDIR` at disk for pip (`setup_board.sh` does this).
- 2 GB RAM -> add swap if anything compiles (`setup_board.sh` handles it).
- Web port is **8090**; the board's `swupdate` service owns 8080.
- A `kill -9` of a `synap_cli_*` process **mid-inference** wedges the NPU
  (`INTERNAL; failed to load HW resources`). Use a clean Ctrl-C; if wedged, kill leftover python/synap
  processes and retry.
