# npu_live

Watch the Coral NPU run, live. A continuous classification loop that makes the NPU's speed tangible: it
classifies every frame on the NPU and shows, in real time, the **measured** inference latency, the
achieved frame rate, and the top-5 labels with confidence bars that react as you move or occlude an
object in front of the camera.

No cloud, no Gemma - just the camera and the NPU. Unplug the network and it keeps running.

## What it does (per frame, in a loop)
1. Grab the latest camera frame (fast: a persistent GStreamer stream).
2. Classify on the NPU - `synap_cli_ic` (MobileNetV2 / ImageNet, top-5).
3. Read the **real** NPU inference time from the SyNAP runtime output (the `inf:` field) and compute the
   actual loop fps.
4. Push the frame + latency (ms) + fps + top-5 confidences to the web page over SSE.

The numbers are measured, not assumed. On the board, `inf` is the pure NPU compute (**~33 ms**, verified);
the loop runs at **~4-5 fps** end-to-end - the limit is the camera/classifier pipeline around the NPU
(the `synap_cli_ic` process reloads the model each call), not the NPU inference itself. The headline is
the latency: the NPU classifies a frame in ~33 ms, locally, on a ~2 W board.

## Run
```bash
# Laptop (camera + NPU mocked, UI alive):
./run_laptop.sh npu                   # open http://localhost:8090

# Board (real camera + real NPU):
./run_board.sh npu                    # open http://<board-ip>:8090
```

Flags: `--top N` (classes to show, default 5), `--max-fps F` (caps the loop rate; keeps the laptop mock
realistic - the board rarely hits the cap).

Dark frames? The OV5647 underexposes indoor scenes. `shared/camera.py` lifts the shadows with a gamma
curve; tune it with `CORAL_CAM_GAMMA` (default `0.40`, lower = brighter) and `CORAL_CAM_BRIGHTEN` (default
`1.5`). Example: `CORAL_CAM_GAMMA=0.30 ./run_board.sh npu`. See `hello_world/README.md` for details.

## What to expect
A big **NPU inference (ms)** number, a **frames/sec** number, and five confidence bars. Move an object
in front of the camera and the bars re-rank and resize each frame while the latency stays in the tens of
milliseconds - that is the point: inference on every frame, locally, with no network.

## Hardware used
Camera (OV5647), NPU classification (`synap_cli_ic`). No LED/buzzer/Gemma. See `../HARDWARE.md`.
