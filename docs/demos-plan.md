# Demos plan — NPU showcase (ready to implement)

Status: **planned, not started.** Demo lineup decided with the maintainer. `hello_world/` stays as the
bring-up self-test; these are the three showcase demos.

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
- **Needs (from the in-progress deep-research):**
  - **ImageNet-1000 → small category buckets** (food / animal / vehicle / electronic / container / …) via
    the WordNet synset hierarchy. Labels are the standard 1000 synsets (`info.json["labels"]`, e.g.
    `'tench, Tinca tinca'`).
  - **Temporal smoothing** so top-1 doesn't flicker frame-to-frame (majority vote / hysteresis over a few
    frames before changing the LED).
- **Feasibility:** high — the fast path. Lowest-risk, most "NPU power" of the three.

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

## Pending before/while implementing

- **Deep-research in progress** on `reflex` (ImageNet→category bucketing, label smoothing, smart-sorter
  references) and `tripwire`/people-counting limits — fold its findings into the `reflex` section when it
  lands.
- Resolve the exact `synapimageproc → synapinfer → appsink` pipeline recipe on the board.
- Confirm grouping: `reflex` + `tripwire` as two demos vs one combined.
