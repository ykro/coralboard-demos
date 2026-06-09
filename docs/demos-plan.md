# Demos plan — NPU showcase

Status: **implemented (2026-06-09), pending board bring-up of the resident pipeline.** All three demos
(`reflex/`, `tripwire/`, `narrator/`) are built and verified end-to-end in `--mock` on a laptop (web page
served, SSE payloads correct, LED/tracker/narration logic exercised). They run on the board today via the
proven per-frame `synap_cli_*` shell-out through `shared/synap_stream.py`; the resident GStreamer pipeline
(the throughput win below) is scaffolded behind `CORAL_SYNAP_RESIDENT=1` with automatic fallback and still
needs its `synapimageproc→synapinfer` caps brought up on real hardware (see "Pending" at the bottom and
`shared/synap_stream.py`). Demo lineup decided with the maintainer. `hello_world/` stays as the bring-up
self-test; these are the three showcase demos.

What landed: `shared/synap_stream.py` (live-vision seam + resident scaffold + Fps), `shared/imagenet_buckets.py`
(static label→category→LED-color table), `shared/tracker.py` (centroid tracker + line crossing), the three
`*/main.py` + `*/web/index.html`, `CORAL_LLM_THREADS` in `gemma_client.py`, and `reflex`/`tripwire`/`narrator`
wired into `run_laptop.sh` / `run_board.sh`.

## The three demos (names)

| Name | Concept | Model / path | Nature |
|------|---------|--------------|--------|
| **`reflex`** | Reactive smart-camera: show an object → classify in ~31 ms → board reacts physically (RGB LED color) + on-screen verdict. Framed as edge industrial inspection / smart-sorter. | MobileNetV2 classification (NPU, fast path) | pure NPU vision |
| **`tripwire`** | Live counter: draw a line/zone, count objects/people crossing it in real time (boxes + running count). | SSD-MobileNet COCO detection (NPU) | pure NPU vision |
| **`narrator`** | Hybrid: NPU does fast vision, Gemma-on-CPU narrates what it sees in one plain sentence (caption refreshes every few seconds). | COCO/MobileNet (NPU) → Gemma 3 270M (CPU) | vision + LLM |

Grouping (maintainer's framing "D + A1, and separately C"): **`reflex` + `tripwire`** are the pure-NPU-vision
pair (both build on the resident GStreamer SyNAP pipeline below); **`narrator`** is the separate hybrid.
*If the intent was a single combined vision demo instead of two, merge `reflex`+`tripwire` — flag before building.*

## Verified board facts that shape the build (measured 2026-06-08)

- **Resident inference is the key win.** The ~4-5 fps cap was `synap_cli_ic/od` reloading the model every
  call. Resident inference times: **classify ~31 ms (~32 fps)**, **detect ~271 ms (~3.7 fps)**, both stable.
- **Resident live-frame inference path = the on-board GStreamer SyNAP plugin** (`/usr/lib/gstreamer-1.0/libgstsynap.so`, v1.22.8):
  `synapimageproc` (preprocess/resize to model input) → `synapinfer` (NPU inference, model resident) →
  `synapoverlay` (draws boxes/labels) / `synapsink`. `synapinfer` props: `model`, `mode` (post-proc),
  `output` (overlay **or json** — JSON is how we read results in Python), `threshold`, `frameinterval`,
  `numinference`. There is **no Python `synap` binding** and `libsynapnb.so` ships **no headers**, so the
  GStreamer plugin is the practical path. The current code shells out to `synap_cli_*` per frame (reloads
  each time) — the showcase demos should move to the persistent pipeline.
- **No power telemetry** (no `/sys/class/hwmon`, no `power_supply`): cannot show a live watt number. ~2 W
  is a spec figure only — cite it, don't claim to measure it.
- **CPU contention is real:** with both A55 cores pegged (e.g. Gemma generating), detect slows 271→377 ms
  (~2.6 fps). RAM is fine (~1.8 GB free; Gemma Q8 ~400 MB fits). Matters for `narrator`.
- **Output is LED only.** The buzzer never auto-fires (ear safety) — `reflex` reacts via the RGB LED.

## Shared infra to build first (used by all three)

**A persistent SyNAP GStreamer inference wrapper** in `shared/` (e.g. `shared/synap_stream.py`): build a
pipeline `v4l2src → synapimageproc → synapinfer(model, output=json) → appsink`, keep the model resident,
and yield parsed JSON results (labels/boxes + confidence) per frame to Python. This replaces the
per-frame `synap_cli_*` shell-out in `shared/vision_labels.py` for the live demos. Reuse `shared/camera.py`
sensor-config logic (auto AE/AGC/AWB) and `shared/webserver.py` (stdlib HTTP + SSE). Keep `--mock`
(laptop) working for every demo.

Open pipeline question to resolve at build time: the exact `synapimageproc`/`synapinfer` caps + how to
surface the JSON to `appsink` (smoke test showed `synapinfer` loads the model and negotiates RGB caps, but
needs `synapimageproc` upstream; no example pipelines ship on the board).

## `reflex` (D) — reactive smart-camera

- **Audience sees:** hold up objects; the board names the category and the RGB LED changes color instantly
  (e.g. food→green, animal→blue, vehicle→red, electronic→white). On-screen: live frame + big category +
  confidence. ~31 ms reaction, faster than expected.
- **Why it proves the NPU:** closes the camera→NPU→physical-action loop at ~32 decisions/s, ~2 W, offline.
  The instant physical reaction makes the speed visceral (not a number readout — that was the retired
  `npu_live`).
- **Build:** MobileNetV2 via the resident pipeline → top-1 → category bucket → `shared/leds.py` color.
- **ImageNet-1000 → small category buckets** (researched): do **not** derive from raw WordNet — it's
  unbalanced (the dog subtree is ~25× the cat subtree) and needs calibration. **Copy a curated mapping:**
  - **Tsipras et al., NeurIPS 2020** ([arXiv:2005.11295](https://arxiv.org/pdf/2005.11295)) — 11 superclasses
    covering all 1000: Dogs (130), Other mammals (88), Bird (59), Reptiles/fish/amphibians (60),
    Invertebrates (61), Food/plants/fungi (63), Devices (172), Structures/furnishing (90), Clothes/covering
    (92), Implements/containers/misc (117), Vehicles (68).
  - or MadryLab **`robustness`** `common_superclass_wnid()` ready-made sets — `mixed_10`
    (Dog/Bird/Insect/Monkey/Car/Cat/Truck/Fruit/Fungus/Boat), `big_12`, etc.
  - For the demo pick ~5-6 buckets → LED colors (a static `class_index → bucket → color` table baked at
    build time; no runtime hierarchy logic).
- **Anti-flicker (researched):** top-1 chatters because >20% of ImageNet images contain multiple objects.
  Mitigate with (a) **hysteresis** — two asymmetric confidence thresholds + a dead band so the LED only
  changes when a new class is *clearly* winning, and (b) **majority vote** over the last N frames; plus the
  stage framing "hold one centered object against a plain background."
- **Feasibility:** high — the fast path. Lowest-risk, most "NPU power" of the three (research confirms D is
  lower-risk than detection-based counting).

## `tripwire` (A1) — live crossing counter

- **Audience sees:** live boxes + a drawn line/zone; a counter increments on each crossing (or a zone-breach
  alert).
- **Why it proves the NPU:** every count is driven by a real per-frame COCO detection.
- **Build:** SSD-MobileNet COCO via the resident pipeline (~3.7 fps) + a **CPU-side centroid tracker**
  between detections to assign IDs and detect line crossings smoothly. `synapoverlay` can draw boxes.
- **Feasibility:** good. ~3.7 detections/s is enough for people/objects crossing a line with the CPU
  tracker interpolating. Note: SSD-MobileNet undercounts dense/overlapping/small subjects (research will
  detail mitigations); keep the scene to a few subjects near the camera.

## `narrator` (C) — hybrid vision + Gemma

- **Audience sees:** live video with NPU detection, and Gemma narrating in one plain sentence ("I see a
  person holding a cup"). Caption refreshes every few seconds.
- **Why it proves the NPU:** the labels/boxes grounding the narration are produced live by the NPU; Gemma
  stays on CPU consuming only text.
- **Build:** resident NPU vision → feed current labels into a grounded Gemma prompt (reuse `hello_world`'s
  scene-grounded prompt approach + `shared/gemma_client.py`).
- **Honest latency:** Gemma 270M on CPU ≈ 6.5 tok/s → a ~20-token sentence ≈ 3-5 s. "Real-time" =
  **smooth live video + caption every ~3-5 s**, not instant. Run vision continuously and invoke Gemma
  periodically (or cap Gemma to 1 thread) to limit the CPU-contention hitch on vision.
- **Feasibility:** works if the few-seconds caption cadence is acceptable (maintainer's condition).

## Pending / resolved

- **[OPEN — board only]** Resolve the exact `synapimageproc → synapinfer → appsink` pipeline recipe on the
  board (the one real unknown; smoke test showed `synapinfer` loads the model + negotiates RGB caps but needs
  `synapimageproc` upstream, and no example pipelines ship on the board). Until then the demos use the
  per-frame `synap_cli_*` shell-out (works, just pays the model reload per call). Bring-up TODO lives in
  `shared/synap_stream.py::_ResidentPipeline`; flip `CORAL_SYNAP_RESIDENT=1` to exercise it.
- **[RESOLVED]** Grouping: built as **two separate demos** (`reflex` + `tripwire`) plus `narrator`, per the
  plan's default. Merge only if the maintainer later wants a single combined vision demo.
- **[CARRIED INTO `tripwire`]** Keep the scene to a few well-separated subjects near the camera — SSD-MobileNet
  undercounts dense/overlapping/small people (true crowd counting needs density-regression models like
  CSRNet, which we can't run; an 80-class SSD is off-paradigm for crowds but fine for sparse crossings). The
  web page hint and the demo docstring both say this.
- **[BOARD CHECK]** Verify on hardware: real ImageNet labels bucket sensibly (the keyword table in
  `imagenet_buckets.py` was tuned against the readable label strings, not the live `info.json`), the LED
  colors read clearly on the on/off RGB LED, and the `narrator` caption cadence + vision smoothness hold with
  `CORAL_LLM_THREADS=1`.
