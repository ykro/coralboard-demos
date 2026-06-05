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
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import (camera, cli, config, gemma_client, leds, textutil,
                    vision_labels, webserver)

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
    completion so the 270M continues the pattern instead of chatting. Kept low
    temperature and guarded so the tiny model doesn't invent times/numbers
    (it loves to start with things like "8:00 AM!")."""
    saw = ", ".join(objs or scene or ["something"])
    prompt = (
        "Greet the user in ONE short, friendly sentence that names ONLY the things "
        "in the list. Do not invent times, numbers, places or anything not listed.\n\n"
        "Things: a keyboard, a mug\n"
        "Greeting: Hello! I can see your keyboard and coffee mug - the board is alive and ready.\n\n"
        "Things: a plant, a window\n"
        "Greeting: Hi there! A little plant and a window over here, and everything checks out.\n\n"
        f"Things: {saw}\nGreeting: "
    )
    out = gemma_client.complete(prompt, max_tokens=48, temperature=0.4,
                                stop=["\n", "Things:", "Greeting:"]).strip()
    # Drop a leading hallucinated time/number prefix ("8:00 AM! ...", "12. ...").
    out = re.sub(r"^\s*\d[\d:apm\.\s]*[!.\-]\s*", "", out, flags=re.I)
    if sum(c.isalpha() for c in out) < 10:  # 270M misfire (empty / digit soup)
        return f"Hello! I can see {saw} over here. The board is alive and ready."
    return out[0].upper() + out[1:] if out else out


def chat(message):
    """Free-form chat with Gemma 3 270M for the web chat box. Kept short so the
    270M on the board's CPU answers in a couple of seconds.

    A 270M often parrots its own instructions back, so we use a clean few-shot
    Q/A format (no visible "system prompt" to copy) and reject any answer that
    echoes the instructions, then retry / fall back."""
    msg = (message or "").strip()[:400]
    if not msg:
        return ""
    prompt = (
        "The following is a short chat with Coralboard, a tiny AI dev board that "
        "runs Gemma 3 270M on its own CPU. Coralboard answers briefly and concretely "
        "in the user's language.\n\n"
        "User: Hello, who are you?\n"
        "Coralboard: I'm Coralboard, a small board running a 270M model right on my own CPU.\n\n"
        "User: How much is 2 + 2?\n"
        "Coralboard: That's 4.\n\n"
        f"User: {msg}\nCoralboard:"
    )
    for temp in (0.6, 0.9):
        raw = gemma_client.complete(prompt, max_tokens=64, temperature=temp,
                                    stop=["User:", "Coralboard:"])
        out = textutil.first_line(textutil.strip_emojis(raw).replace("*", ""))
        if out and not _echoes_prompt(out):
            return out
    return "I'm a tiny 270M model running on this board - try asking that a bit differently."


def _echoes_prompt(text):
    """True if the model parroted the instructions instead of answering."""
    low = text.lower()
    return any(s in low for s in (
        "you are the coralboard", "tiny ai dev board", "reply in the same language",
        "the following is a short chat", "answers briefly", "no markdown"))


def _on_action(params):
    """Handle the web page's controls.
    GET /action?do=led&color=..  | do=buzz&ms=..  | do=chat&msg=..
    Returning a dict sends it back to the browser as JSON."""
    action = params.get("do")
    if action == "led":
        leds.set_color("#" + params.get("color", "ffffff"))
    elif action == "buzz":
        return {"buzzing": leds.buzz_toggle()}   # toggle on/off; report new state
    elif action == "chat":
        return {"reply": chat(params.get("msg", ""))}


def main():
    parser = argparse.ArgumentParser(description="The Coralboard's hello world (camera + NPU + LEDs + buzzer + Gemma)")
    cli.add_common_args(parser)
    parser.add_argument("--image", default=None, help="use this JPEG instead of the camera")
    args = parser.parse_args()
    cli.apply_common_args(args)

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))
    webserver.set_action_handler(_on_action)   # LED/buzzer buttons on the web page
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

    leds.set_color("#00ff00")  # done: green (each channel is on/off, so use a pure color)
    # No auto-buzz: the buzzer never sounds on its own (CORAL_BUZZER_ENABLE opt-in only).

    def _payload(photo, scene, dets, greeting):
        return {
            "type": "hello", "steps": steps,
            "scene": scene or [],
            "objects": [d.get("label_en") or d["label"] for d in (dets or [])],
            "boxes": [{"label": d.get("label_en") or d["label"],
                       "x": d["box"]["x"], "y": d["box"]["y"],
                       "w": d["box"]["w"], "h": d["box"]["h"],
                       "conf": d["confidence"]} for d in (dets or [])],
            "greeting": greeting, "photo": "/photo.jpg",
            "mode": "MOCK" if config.MOCK else "BOARD",
        }

    webserver.set_photo(photo)
    webserver.broadcast(_payload(photo, scene, dets, hello))
    print(f"web up at http://<board-ip>:{config.WEB_PORT}  ·  Ctrl-C to quit")

    # Live refresh: keep re-capturing + re-classifying so the page shows a live
    # frame instead of a single frozen shot. Skipped when a fixed --image is used.
    refresh = float(os.environ.get("CORAL_REFRESH_SEC", "2.5"))
    try:
        while True:
            time.sleep(refresh)
            if args.image:
                continue
            try:
                camera.capture_frame(FRAME)
                scene = vision_labels.scene_labels(FRAME)
                dets = vision_labels.object_detect(FRAME, min_conf=0.35)
            except Exception:
                continue          # transient capture/NPU hiccup: keep the last frame
            webserver.set_photo(FRAME)
            webserver.broadcast(_payload(FRAME, scene, dets, hello))
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        leds.buzz_off()    # never leave the buzzer sounding after we exit
        camera.release()   # free /dev/video0 so the next run captures cleanly


if __name__ == "__main__":
    main()
