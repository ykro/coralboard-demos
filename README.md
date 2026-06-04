# coralboard-demos

Two self-contained demos for the **Synaptics Coralboard** (Astra SL2619 + Coral NPU "TORQ"), built to
show what the board's NPU can do on-device, with nothing but the board, its Sensor HAT shield, and the
OV5647 camera. No cloud, no torch.

Both demos run on a laptop with `--mock` (so you can read the output and the web UI without the board),
and on the board for real. Vision runs on the NPU via the two preinstalled SyNAP models; Gemma 3 270M
runs on the CPU via llama.cpp.

| Demo | What it shows | Uses |
|------|---------------|------|
| [`hello_world/`](hello_world/) | The board's "hello world" / bring-up self-test: camera, NPU classify + detect, RGB LED, buzzer, and a Gemma greeting, all in one run. | camera + NPU (both models) + LED + buzzer + Gemma + web |
| [`npu_live/`](npu_live/) | The NPU's speed, live: continuous classification with the real measured inference latency (ms), the achieved fps, and top-5 confidence bars that react as you move an object. | camera + NPU (classification) + web |

See [`HARDWARE.md`](HARDWARE.md) for the verified board details (NPU models, LED/buzzer wiring, camera,
board access) needed to reproduce these.

## Quickstart - laptop (mocked hardware, real models)

```bash
./models/fetch_models.sh        # one-time: download the Gemma 3 270M GGUF (~291 MB)
./run_laptop.sh hello           # then open http://localhost:8090
./run_laptop.sh npu             # then open http://localhost:8090
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
./run_board.sh npu
```

The board has no Wi-Fi; reach the web page over USB networking. To give the board internet for setup,
run `./net_board_internet.sh` from the Mac (one command). Details in `HARDWARE.md`.

## Layout
```
shared/        camera, vision (NPU), Gemma client, LEDs/buzzer, web server, config
hello_world/   demo 1 (main.py + web/)
npu_live/      demo 2 (main.py + web/)
models/        fetch_models.sh (Gemma GGUF; weights are not in git)
*.sh           run_laptop / setup_board / copy_to_board / net_board_internet
```

## Notes
- All vision is on the **NPU** (`synap_cli_ic` / `synap_cli_od`). No CPU fallback, no torch.
- The web server is stdlib only (`http.server` + SSE) - nothing to install on the board for the UI.
- Output, UI, and code are in English.
