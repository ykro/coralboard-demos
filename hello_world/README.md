# hello_world

The Coralboard's "hello, world". The smallest demo that exercises every part of the board at once, so it
also works as a bring-up self-test: run it first to confirm your board is alive.

## What it does (one pass)
1. **Camera** - capture one frame from the OV5647 (`shared/camera.py`, GStreamer).
2. **NPU classify** - `synap_cli_ic` (MobileNetV2 / ImageNet) names the scene (~33 ms inference).
3. **NPU detect** - `synap_cli_od` (COCO) finds objects + boxes.
4. **Gemma 3 270M** - writes a one-line greeting about what it saw (CPU, llama.cpp).
5. **Output** - sets the RGB status LED (blue while booting -> amber while thinking -> green when done),
   beeps the buzzer, and pushes the frame + boxes + greeting + a per-subsystem status list to a local web
   page.

Each step is wrapped so a missing subsystem shows a clear status line instead of crashing.

## Run
```bash
# Laptop (hardware mocked, Gemma real):
./run_laptop.sh hello                 # open http://localhost:8090

# Board (real hardware):
./run_board.sh hello                  # open http://<board-ip>:8090
./run_board.sh hello --image foo.jpg  # use a fixed JPEG instead of the camera
```

## What to expect
- Console: a `[ok]`/`[!!]` line per subsystem, then the greeting.
- Web page: the captured frame with green detection boxes, the greeting, and the status list. On the
  board you should also see the RGB LED turn **green** and hear a short **beep** at the end.

## Hardware used
Camera (OV5647), NPU (both preinstalled SyNAP models), RGB status LED (`/sys/class/leds/*:status`),
buzzer (`BUZZERn`, gpiochip0 line 6, via `gpioset`), Gemma 3 270M on the A55 cores. See `../HARDWARE.md`.

## Relevant env vars
- `CORAL_LED_RED` / `CORAL_LED_GREEN` / `CORAL_LED_BLUE` - LED class names (defaults `*:status`).
- `CORAL_BUZZER_CHIP` / `CORAL_BUZZER_LINE` / `CORAL_BUZZER_ON` - buzzer GPIO line + active value.
- `CORAL_WEB_PORT` - web port (default 8090).
