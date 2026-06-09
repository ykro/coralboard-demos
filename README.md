# coralboard-demos

Self-contained demos for the **Synaptics Coralboard** (Astra SL2619 + Coral NPU "TORQ"), built to
show what the board's NPU can do on-device, with nothing but the board, its Sensor HAT shield, and the
OV5647 camera. No cloud, no torch.

Vision runs on the NPU via the two preinstalled SyNAP models; Gemma 3 270M runs on the CPU via llama.cpp.

## Two ways to run — laptop vs board

Every demo runs in one of two places, and **the laptop (mocked) path is the default**:

| | **Laptop (default)** | **Board (real hardware)** |
|---|---|---|
| Command | `./run_laptop.sh <demo>` or `./demo.sh` | `./run_board.sh <demo>` or `./demo.sh --board <demo>` |
| Hardware | camera/LED/buzzer **mocked** (synthetic frames + labels) | real OV5647 camera, NPU, RGB LED, buzzer |
| Gemma | **real** (the same GGUF the board uses) | real (on the A55 CPU) |
| Needs the board? | **No** — try the demos with zero hardware | Yes, over USB (`adb`) |

`./demo.sh` (no args) shows a menu and runs on the **laptop** unless you pass `--board`. Use the laptop path
to explore the UI and logic without hardware; use the board path for the real on-device demo. A beginner
**with the board** should still run the laptop path once first (it needs no setup), then follow
**First run: test hello_world over USB** below.

| Demo | What it shows | Uses |
|------|---------------|------|
| [`hello_world/`](hello_world/) | The board's "hello world" / bring-up self-test: camera, NPU classify + detect, RGB LED, buzzer, and a Gemma greeting, all in one run. | camera + NPU (both models) + LED + buzzer + Gemma + web |
| [`reflex/`](reflex/) | **Reactive smart-camera.** Hold up an object → NPU classifies it in ~31 ms → the board reacts physically: the RGB LED changes color by category (food→green, animal→blue, vehicle→red, device→white, clothing→magenta, other→cyan) and the page shows the verdict + top-5 + live NPU latency. | camera + NPU classify + LED + web |
| [`tripwire/`](tripwire/) | **Live crossing counter.** Draw a line on the page; the NPU detects COCO objects each frame and a CPU centroid tracker counts each object that crosses, per direction. | camera + NPU detect + web |
| [`narrator/`](narrator/) | **Hybrid vision + LLM.** The NPU runs the vision continuously while Gemma 3 270M on the CPU narrates the scene in one plain sentence, refreshed every few seconds. | camera + NPU detect + Gemma + web |

`hello_world` is the bring-up self-test; **`reflex` + `tripwire`** are the pure-NPU-vision showcase pair and
**`narrator`** is the vision+LLM hybrid. The plan and per-demo design notes are in
[`docs/demos-plan.md`](docs/demos-plan.md).

See [`HARDWARE.md`](HARDWARE.md) for the verified board details (NPU models, LED/buzzer wiring, camera,
board access) needed to reproduce these.

## Prerequisites

Install these on your computer first, then get the repo:

- **git** and **Python 3** (3.10+). Needed for both the laptop and board paths.
- **adb** (Android platform-tools) — only for the **board** path; it's how you reach the headless board.
  macOS: `brew install android-platform-tools`. Linux: `sudo apt install android-tools-adb` (or your
  distro's package). Windows: install Google's "SDK Platform-Tools" and add it to PATH. Verify with
  `adb version`.

```bash
git clone https://github.com/ykro/coralboard-demos.git
cd coralboard-demos
```

The laptop path needs nothing else (`run_laptop.sh` builds its own `.venv`). The board path additionally
needs the board reachable over USB — see **First run** below.

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
  Host["computer<br/>browser + adb"]
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

### The showcase demos

The three showcase demos share one live-vision seam, `shared/synap_stream.py`: it grabs a frame and runs
NPU inference per loop, returning parsed results + the JPEG to show. Today it uses the proven per-frame
`synap_cli_*` shell-out (same path as `hello_world`); a resident-model GStreamer pipeline that keeps the
NPU model loaded (classify ~31 ms / detect ~271 ms) is scaffolded behind `CORAL_SYNAP_RESIDENT=1` and
falls back automatically until its caps are brought up on the board (see the module and `docs/demos-plan.md`).

```mermaid
flowchart LR
  cam["camera frame"] --> vs["shared/synap_stream<br/>(NPU classify / detect)"]
  vs --> reflex["reflex<br/>label → category bucket → LED color<br/>(hysteresis + majority vote)"]
  vs --> trip["tripwire<br/>centroid tracker → line crossing count"]
  vs --> narr["narrator<br/>labels → Gemma 270M (CPU) → caption"]
  reflex & trip & narr --> web["live web page (SSE)"]
```

- **`reflex`** debounces the chattering top-1 with a majority vote over N frames + a confidence floor to
  enter a new category (a dead band), so the LED only flips when a category is clearly, repeatedly winning.
  ImageNet→category mapping is a static keyword table in `shared/imagenet_buckets.py`.
- **`tripwire`** tracks centroids on the CPU between detections (`shared/tracker.py`) to assign stable IDs
  and detect line crossings. Keep the scene to a few well-separated subjects — an 80-class SSD undercounts
  dense/overlapping subjects.
- **`narrator`** runs vision and Gemma on separate threads; `run_board.sh` sets `CORAL_LLM_THREADS=1` for it
  so generating a caption leaves a core free for the vision loop. It warms the camera before loading Gemma,
  so the live video is up in a few seconds; the **first caption** then waits ~10-15 s for the model to load
  on the CPU, and after that refreshes every few seconds (270M on CPU ≈ 6.5 tok/s) — not instant.

### Gemma 3 270M on the CPU: what to expect (and its limits)

Gemma 3 270M is a **270-million-parameter** model running on the board's two Cortex-A55 cores via
llama.cpp — chosen because it fits in RAM and runs fully on-device, **not** because it's capable. Expect:

- **It is slow on this CPU (~6.5 tokens/second).** So in **`narrator`**: the live video (NPU) is smooth, but
  the *caption* is text generation on the CPU. The **first caption takes ~10-15 s** (the model has to load),
  and each refresh after that takes **~3-5 s** for a one-sentence caption. The caption therefore **lags the
  video by a few seconds and only updates every few seconds** — this is the model being slow, not a hang or a
  bug. Detection also drops from ~3.7 fps toward ~2.6 fps while Gemma is generating (both A55 cores busy).
- **The chat (in `hello_world`) is very limited.** A 270M model often **answers in English even when asked in
  Spanish**, **repeats itself** on open-ended questions, and **makes things up** — e.g. it may emit a
  placeholder like `123 Main Street, Anytown, USA` when it has nothing real to say. That's why the chat is
  **grounded in what the camera/NPU currently sees** ("what do you see?" answers concretely) and the code
  guards/retries the worst misfires. Treat it as a *demo that an LLM can run on-device*, not a useful
  assistant. For better text quality you would run a larger model off-device — out of scope here.

## Quickstart - laptop (mocked hardware, real models)

```bash
./models/fetch_models.sh                      # one-time: download the Gemma 3 270M GGUF (~291 MB)
./run_laptop.sh hello                          # then open http://localhost:8090
./run_laptop.sh reflex                         # or: reflex | tripwire | narrator
```

`run_laptop.sh` creates a `.venv` on first run. `--mock` fakes the camera/LED/buzzer and the NPU (it
cycles plausible labels/detections) but keeps **Gemma real** - the same GGUF that runs on the board.
`reflex` and `tripwire` are pure NPU vision (no model needed in mock); `narrator` and `hello` use Gemma
(add `--backend template` for a no-model run). Each demo serves its own page on the same port.

Or pick from a menu with `./demo.sh` — it runs on your **laptop (mocked hardware)** by default; add
`--board` to run on the real board instead (`./demo.sh --board reflex`).

## First run: test hello_world over USB (real camera + real NPU)

Use this the first time you plug the board into your computer, to confirm the whole board works. Hardware
hookup (camera + Sensor HAT + USB) is in [`HARDWARE.md`](HARDWARE.md) → **Connecting the hardware**.

1. **Confirm the board is connected:**
   ```bash
   adb devices                 # expect:  grinn-astra-2619-coral   device
   ```
   If it's empty, see HARDWARE.md (replug, data cable, etc.).

2. **Give the board internet over USB** (do this *before* setup). The board has no Wi-Fi, and
   `setup_board.sh` downloads pip wheels + the Gemma weight, so it needs a connection first:
   ```bash
   ./net_board_internet.sh     # shares your computer's internet to the board over USB
   ```
   > **macOS only.** `net_board_internet.sh` uses macOS tools (`networksetup`/`pfctl`). On **Linux/Windows**,
   > enable your OS's internet connection sharing on the USB/RNDIS interface toward the board's subnet
   > (board `usb0` = `192.168.137.2`, set your USB-gadget interface to `192.168.137.1`, NAT to your upstream,
   > and set the board's default route + DNS). See HARDWARE.md → **Board access**.

3. **Fetch the Gemma weight on your computer** (it's git-ignored, so `copy_to_board.sh` ships it only if
   it's already here):
   ```bash
   ./models/fetch_models.sh    # downloads the Gemma 3 270M GGUF (~291 MB)
   ```

4. **Copy the code to the board** (run from this repo on your computer):
   ```bash
   ./copy_to_board.sh          # git archive HEAD + adb push -> /home/root/coralboard-demos
   ```
   `copy_to_board.sh` ships `git archive HEAD`, so **commit first** or your edits won't go over. It also
   pushes the GGUF fetched in step 3.

5. **Set up + run on the board** (over adb):
   ```bash
   adb shell
   cd /home/root/coralboard-demos
   ./setup_board.sh            # one-time: venv + Gemma wheel + NPU sanity check (needs the internet from step 2)
   ./run_board.sh hello        # starts the demo; leave it running
   ```
   If pip times out here, the board has no internet yet — redo step 2, then re-run `./setup_board.sh`.

6. **Open the web page from your computer.** Forward the port over adb (in a second terminal on your
   computer):
   ```bash
   adb forward tcp:8090 tcp:8090
   ```
   Then open **http://localhost:8090**. If the demo printed `Address already in use`, port 8090 is taken —
   stop the other process or run with another port: `CORAL_WEB_PORT=8095 ./run_board.sh hello` (forward 8095).

**What you should see**
- Console: one `[ok]`/`[!!]` line per subsystem (camera, NPU classify, NPU detect, Gemma), then a
  one-line greeting. Startup is **silent** (no beep).
- Web page: the live camera frame with green detection boxes, the detected scene/objects, the greeting,
  and the per-subsystem status list. The **RGB LED** turns green when the first pass finishes. The buzzer
  only sounds if you press the **Buzz** toggle yourself.
- A `[!!]` line means that one subsystem degraded (e.g. camera unplugged) — the demo keeps running and the
  line tells you what failed.

**Stop it cleanly:** `Ctrl-C` in the run shell. Never `kill -9` a `synap_cli_*` mid-inference (it wedges
the NPU). To redeploy code changes: `Ctrl-C`, `./copy_to_board.sh` (after committing), then `./run_board.sh hello` again.

**If a demo prints `(... hiccup)` over and over**, the NPU is most likely wedged from an earlier `kill -9`
(the demo also prints a one-line recovery hint after several hiccups): kill any leftover `python`/`synap_cli_*`
processes on the board (`pkill -f synap_cli; pkill -f run_board`) and run the demo again.

Prefer to try it without the board first? `./run_laptop.sh hello` runs the same demo with mocked hardware
(real Gemma) — see the laptop quickstart above.

Once `hello` confirms the board, the showcase demos run the same way — swap the name:
`./run_board.sh reflex` (hold objects to the camera; watch the LED), `./run_board.sh tripwire` (draw the
line on the page; walk objects across it), `./run_board.sh narrator` (let it describe the scene). Same port
8090, same `adb forward`, same clean `Ctrl-C` to stop.

**One command from your computer:** `./run_on_board.sh reflex` does the whole board flow at once — checks the
board over adb, forwards the web port, opens your browser, and runs the demo on the board in the foreground
so `Ctrl-C` stops it cleanly. Add `--deploy` to copy the latest committed code over first, pass a port as a
second arg, or run it with no demo name for a menu (`./run_on_board.sh`). This is the board counterpart of
`./demo.sh` (which runs on the laptop).

## Layout
```
shared/        camera, vision (NPU), synap_stream (live-vision seam), imagenet_buckets,
               tracker, Gemma client, LEDs/buzzer, web server, config
hello_world/   bring-up self-test (main.py + web/)
reflex/        reactive smart-camera (main.py + web/)
tripwire/      live crossing counter (main.py + web/)
narrator/      NPU vision + Gemma narration (main.py + web/)
models/        fetch_models.sh (Gemma GGUF; weights are not in git)
*.sh           run_laptop / run_board / setup_board / copy_to_board / net_board_internet
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
