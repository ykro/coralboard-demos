# coralboard-demos

Self-contained demos for the **Synaptics Coralboard** (Astra SL2619 + Coral NPU "TORQ"), built to
show what the board's NPU can do on-device, with nothing but the board, its Sensor HAT shield, and the
OV5647 camera. No cloud, no torch.

The demo runs on a laptop with `--mock` (so you can read the output and the web UI without the board),
and on the board for real. Vision runs on the NPU via the two preinstalled SyNAP models; Gemma 3 270M
runs on the CPU via llama.cpp.

| Demo | What it shows | Uses |
|------|---------------|------|
| [`hello_world/`](hello_world/) | The board's "hello world" / bring-up self-test: camera, NPU classify + detect, RGB LED, buzzer, and a Gemma greeting, all in one run. | camera + NPU (both models) + LED + buzzer + Gemma + web |

See [`HARDWARE.md`](HARDWARE.md) for the verified board details (NPU models, LED/buzzer wiring, camera,
board access) needed to reproduce these.

## Architecture

### The board

The Astra **SL2619** runs everything on-device: vision on the Coral NPU, Gemma on the two A55 cores, and
the peripherals over the Sensor HAT. No Wi-Fi - you reach it over USB (adb + USB networking).

```mermaid
flowchart TB
  subgraph Board["Synaptics Coralboard (Astra SL2619, ~1.9 GB RAM, ~2 W)"]
    direction TB
    NPU["Coral NPU TORQ<br/>SyNAP runtime<br/>(2 preinstalled models only)"]
    CPU["2x Cortex-A55<br/>Gemma 3 270M (llama.cpp)<br/>+ Python web server"]
    subgraph HAT["Sensor HAT + CSI"]
      CAM["OV5647 camera (CSI)"]
      LED["RGB status LED<br/>/sys/class/leds/*:status"]
      BUZ["Buzzer<br/>gpiochip0 line 6"]
      MIC["Mics (no speaker)"]
      BTN["User button"]
    end
  end
  Host["Mac / laptop<br/>browser + adb"]
  CAM --> NPU
  NPU --> CPU
  CPU --> LED & BUZ
  CPU -- "HTTP :8090 + SSE" --> Host
  Host -- "adb (root) / USB net 192.168.137.x" --> CPU
```

Hard constraint: the NPU runs **only the 2 preinstalled SyNAP models** (no SL2619 target in the toolkit),
so a demo's value comes from **speed + locality + combining the NPU with on-CPU Gemma**, not a custom model.

### The demo

```mermaid
flowchart LR
  subgraph H["hello_world (one self-test pass, then live)"]
    direction TB
    h1["camera frame"] --> h2["NPU classify (synap_cli_ic)"]
    h1 --> h3["NPU detect (synap_cli_od)"]
    h2 & h3 --> h4["Gemma greeting (CPU)"]
    h4 --> h5["LED + buzzer + web card"]
    h5 -. "refresh every ~2.5s" .-> h1
    web1["web controls: LED / buzz toggle /<br/>scene-grounded Gemma chat (/action)"] --> h4
  end
```

`hello_world` exercises every subsystem once (bring-up self-test), then keeps the camera frame live and
exposes web controls (LED, buzzer, and an on-device **Gemma chat box**). It uses `shared/`
(camera, vision, Gemma client, LEDs/buzzer, web server, config).

## Quickstart - laptop (mocked hardware, real models)

```bash
./models/fetch_models.sh        # one-time: download the Gemma 3 270M GGUF (~291 MB)
./run_laptop.sh hello           # then open http://localhost:8090
```

`run_laptop.sh` creates a `.venv` on first run. `--mock` fakes the camera/LED/buzzer and the NPU (it
cycles plausible labels) but keeps **Gemma real** - the same GGUF that runs on the board.

## Quickstart - board (real camera + real NPU)

```bash
./copy_to_board.sh              # git archive + adb push -> /home/root/coralboard-demos
# then, on the board (adb shell):
cd /home/root/coralboard-demos
./setup_board.sh                # venv + Gemma wheel + GGUF + NPU sanity check
./run_board.sh hello            # open http://<board-ip>:8090
```

The board has no Wi-Fi; reach the web page over USB networking. To give the board internet for setup,
run `./net_board_internet.sh` from the Mac (one command). Details in `HARDWARE.md`.

## Layout
```
shared/        camera, vision (NPU), Gemma client, LEDs/buzzer, web server, config
hello_world/   the demo (main.py + web/)
models/        fetch_models.sh (Gemma GGUF; weights are not in git)
*.sh           run_laptop / setup_board / copy_to_board / net_board_internet
```

## Notes
- All vision is on the **NPU** (`synap_cli_ic` / `synap_cli_od`). No CPU fallback, no torch.
- The web server is stdlib only (`http.server` + SSE) - nothing to install on the board for the UI.
- Output, UI, and code are in English.
- **Buzzer (read this):** the buzzer is **active-low** (`gpiochip0` line 6: `0` sounds, `1` is silent) and
  this board **latches** the last written value. It **never sounds on its own** - there is no startup beep
  and nothing triggers it but the web **Buzz** button, which is a **toggle** (press to sound, press again to
  stop). A safety timer forces it off after `CORAL_BUZZER_MAX_SEC` (default 12 s), the demo silences it on
  exit, and `CORAL_BUZZER_ENABLE=0` hard-disables it. Panic-silence by hand: `gpioset gpiochip0 6=1`.
  Polarity overrides: `CORAL_BUZZER_ON` / `CORAL_BUZZER_IDLE`.
- **Camera:** the OV5647's exposure/gain/white-balance controls live on the **sensor subdev**
  (`/dev/v4l-subdev*`), *not* on `/dev/video0` (which only has `wb_enable`). The sensor powers up in manual
  mode at near-minimum gain - so it gives near-black frames, and lifting those in software amplifies the
  noise floor into coloured "static". The fix is in hardware: `shared/camera.py` switches the sensor to
  **auto exposure / auto gain / auto white-balance** on every stream start (via `v4l2-ctl` on the sensor
  subdev), then software adds only a gentle gamma. Result: bright, neutral, low-noise frames that adapt to
  the light. Tune: `CORAL_CAM_AE`/`AGC`/`AWB` (auto, default 1), `CORAL_CAM_GAIN`/`CORAL_CAM_EXPOSURE`
  (manual when auto off), `CORAL_CAM_GAMMA` (0.6), `CORAL_CAM_JPEG_Q` (92). The OV5647 is still a modest
  sensor (soft, noisy in true low light) but no longer broken.
- **Deploying changes:** `copy_to_board.sh` ships `git archive HEAD`, so **commit first** or your edits
  won't go over. A running demo holds the old code in memory - **restart it** (`Ctrl-C` then
  `./run_board.sh ...`) to pick up new code. To view the page without USB networking:
  `adb forward tcp:8090 tcp:8090` then open `http://localhost:8090`.
