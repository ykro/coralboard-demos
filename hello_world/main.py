"""hello_world - the Coralboard's "hello, world".

The smallest demo that exercises EVERY part of the board at once, so it doubles
as a bring-up self-test: run it first to confirm your board works.

  camera  -> capture one frame                          (OV5647 CSI)
  NPU     -> classify the scene  (synap_cli_ic)  AND     (Coral NPU, 2 models)
             detect objects      (synap_cli_od)
  Gemma   -> one-line greeting about what it saw         (Gemma 3 270M, CPU)
  output  -> RGB status LED + buzzer beep + a live web card

Every subsystem is wrapped so a missing piece degrades to a clear status line
instead of crashing.

Laptop (hardware mocked, Gemma real):   ./run_laptop.sh hello
Board (real hardware):                  ./run_board.sh hello
Board with a fixed image (no camera):   ./run_board.sh hello --image /path/to.jpg
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import (camera, cli, config, gemma_client, leds, vision_labels,
                    webserver)

FRAME = os.path.join(os.path.dirname(__file__), "..", "captures", "hello.jpg")


def _step(name, fn):
    """Run one subsystem check; never raises. Returns (status_dict, value)."""
    try:
        value = fn()
        return {"name": name, "ok": True, "detail": ""}, value
    except Exception as e:
        return {"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"[:90]}, None


def greeting(scene, objs):
    """Ask Gemma for a one-line greeting about what the NPU saw. Few-shot +
    completion so the 270M continues the pattern instead of chatting."""
    saw = ", ".join(objs or scene or ["something"])
    prompt = (
        "You are a small board introducing yourself by naming what you SEE, in "
        "ONE short, friendly sentence. Do not repeat the instructions.\n\n"
        "I see: a keyboard, a mug\n"
        "Greeting: Hello! I can see your keyboard and coffee mug. The board is alive and ready.\n\n"
        "I see: a plant, a window\n"
        "Greeting: Hi there! A little plant and some nice light over here. Everything checks out.\n\n"
        f"I see: {saw}\nGreeting: "
    )
    out = gemma_client.complete(prompt, max_tokens=48, temperature=0.7,
                                stop=["\n", "I see:", "Greeting:"]).strip()
    if sum(c.isalpha() for c in out) < 10:  # 270M misfire (empty / digit soup)
        return f"Hello! I can see {saw} over here. The board is alive and ready."
    return out


def main():
    parser = argparse.ArgumentParser(description="The Coralboard's hello world (camera + NPU + LEDs + buzzer + Gemma)")
    cli.add_common_args(parser)
    parser.add_argument("--image", default=None, help="use this JPEG instead of the camera")
    args = parser.parse_args()
    cli.apply_common_args(args)

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))
    print("hello_world - board self-test\n")
    steps = []

    leds.set_color("#6c63ff")  # booting: blue/purple
    cam_status, photo = _step(
        "camera (OV5647)",
        lambda: args.image if args.image else camera.capture_frame(FRAME))
    photo = photo or (args.image or FRAME)
    cam_status["detail"] = "frame captured" if cam_status["ok"] else cam_status["detail"]
    steps.append(cam_status)

    ic_status, scene = _step("NPU classify (synap_cli_ic)",
                             lambda: vision_labels.scene_labels(photo))
    ic_status["detail"] = ", ".join(scene) if scene else ic_status["detail"]
    steps.append(ic_status)

    od_status, dets = _step("NPU detect (synap_cli_od)",
                            lambda: vision_labels.object_detect(photo, min_conf=0.35))
    objs = [d.get("label_en") or d["label"] for d in (dets or [])]
    od_status["detail"] = ", ".join(objs) if objs else (od_status["detail"] or "no objects")
    steps.append(od_status)

    leds.set_color("#f2c14e")  # thinking: amber
    gem_status, hello = _step("Gemma 3 270M", lambda: greeting(scene, objs))
    hello = hello or "Hello! The board is alive."
    gem_status["detail"] = f"backend={config.BACKEND}"
    steps.append(gem_status)

    for s in steps:
        print(f"{'[ok]' if s['ok'] else '[!!]'} {s['name']:<30} {s['detail']}")
    print(f"\n{hello}\n")

    leds.set_color("#3ddc84")  # done: green
    leds.buzz(120)
    webserver.set_photo(photo)
    webserver.broadcast({
        "type": "hello", "steps": steps,
        "scene": scene or [], "objects": objs,
        "boxes": [{"label": d.get("label_en") or d["label"],
                   "x": d["box"]["x"], "y": d["box"]["y"],
                   "w": d["box"]["w"], "h": d["box"]["h"],
                   "conf": d["confidence"]} for d in (dets or [])],
        "greeting": hello, "photo": "/photo.jpg",
        "mode": "MOCK" if config.MOCK else "BOARD",
    })
    print(f"web up at http://<board-ip>:{config.WEB_PORT}  ·  Ctrl-C to quit")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
