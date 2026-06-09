"""narrator - hybrid NPU vision + Gemma narration.

The NPU runs the vision continuously (detection boxes refresh smoothly on the
page); a background thread feeds the current labels to Gemma 3 270M on the CPU,
which writes one plain sentence about the scene ("I see a person holding a cup").
The caption refreshes every few seconds.

Why this proves the NPU: the labels/boxes that ground the narration are produced
live by the NPU; Gemma stays on the CPU consuming only TEXT. Honest latency: a
270M on two A55 cores does ~6.5 tok/s, so a ~20-token sentence takes ~3-5 s --
"real-time" here means smooth live video with a caption every few seconds, not an
instant caption. Vision and Gemma run on separate threads, and CORAL_LLM_THREADS=1
(set by run_board.sh for this demo) leaves a core for the vision loop so the video
doesn't hitch while Gemma is generating.

Laptop (mocked NPU, REAL Gemma):  ./run_laptop.sh narrator
Board (real NPU + Gemma on CPU):  ./run_board.sh narrator
"""

import argparse
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import (cli, config, gemma_client, leds, synap_stream, textutil,
                    webserver)

FRAME = os.path.join(os.path.dirname(__file__), "..", "captures", "narrator.jpg")

# Shared state between the vision loop and the narration thread.
_state = {"labels": [], "caption": "Looking around...", "thinking": False,
          "gen_ms": 0.0}
_lock = threading.Lock()


def narrate(labels):
    """One plain sentence about what the NPU sees. Few-shot completion so the
    270M continues the pattern instead of chatting; guarded against the empty /
    digit-soup misfires a tiny model produces."""
    saw = ", ".join(labels) if labels else "an empty scene"
    prompt = (
        "Describe what the camera sees in ONE short, plain sentence. Mention only "
        "the things in the list. Do not invent anything not listed.\n\n"
        "Things: person, cup\n"
        "Caption: I can see a person holding a cup.\n\n"
        "Things: laptop, keyboard, mouse\n"
        "Caption: There's a laptop with a keyboard and a mouse on the desk.\n\n"
        "Things: dog\n"
        "Caption: A dog is sitting in front of the camera.\n\n"
        f"Things: {saw}\nCaption: "
    )
    out = gemma_client.complete(prompt, max_tokens=40, temperature=0.5,
                                stop=["\n", "Things:", "Caption:"]).strip()
    out = textutil.first_line(textutil.strip_emojis(out).replace("*", ""))
    out = re.sub(r"^\s*\d[\d:apm\.\s]*[!.\-]\s*", "", out, flags=re.I)
    if sum(c.isalpha() for c in out) < 8:   # 270M misfire
        return f"I can see {saw}." if labels else "I don't see anything in particular right now."
    return out[0].upper() + out[1:]


def _narration_loop(stop_evt, period):
    """Background: every `period` seconds, narrate the latest labels."""
    last_key = None
    while not stop_evt.is_set():
        with _lock:
            labels = list(_state["labels"])
            caption_now = _state["caption"]
        key = tuple(sorted(labels))
        # Re-narrate on a timer, but skip if the scene is identical to last time
        # (saves a CPU-heavy generation when nothing changed).
        if key != last_key or caption_now == "Looking around...":
            with _lock:
                _state["thinking"] = True
            t0 = time.monotonic()
            try:
                caption = narrate(labels)
            except Exception as e:
                caption = f"(narration unavailable: {type(e).__name__})"
            gen_ms = (time.monotonic() - t0) * 1000.0
            with _lock:
                _state["caption"] = caption
                _state["thinking"] = False
                _state["gen_ms"] = gen_ms
            last_key = key
        stop_evt.wait(period)


def _payload(res, fps):
    items = res.get("items", [])
    with _lock:
        caption, thinking, gen_ms = _state["caption"], _state["thinking"], _state["gen_ms"]
    return {
        "type": "narrator",
        "boxes": [{"label": d.get("label_en") or d.get("label"),
                   "x": d["box"]["x"], "y": d["box"]["y"],
                   "w": d["box"]["w"], "h": d["box"]["h"],
                   "conf": d["confidence"]} for d in items if "box" in d],
        "labels": [d.get("label_en") or d.get("label") for d in items],
        "caption": caption, "thinking": thinking,
        "gen_ms": round(gen_ms), "fps": round(fps, 1),
        "photo": "/photo.jpg",
        "mode": "MOCK" if config.MOCK else "BOARD",
    }


def main():
    parser = argparse.ArgumentParser(description="narrator - NPU vision + Gemma narration (hybrid)")
    cli.add_common_args(parser)
    parser.add_argument("--narrate-sec", type=float,
                        default=float(os.environ.get("CORAL_NARRATE_SEC", "4")),
                        help="seconds between Gemma caption refreshes")
    parser.add_argument("--min-conf", type=float,
                        default=float(os.environ.get("CORAL_NARRATOR_CONF", "0.35")))
    args = parser.parse_args()
    cli.apply_common_args(args)

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))

    stream = synap_stream.VisionStream(FRAME)
    fps = synap_stream.Fps()
    interval = float(os.environ.get("CORAL_NARRATOR_INTERVAL", "0.1"))

    # Warm the camera BEFORE the narration thread loads Gemma. The camera's
    # first-frame warmup (the persistent GStreamer pipeline settling auto-exposure)
    # is CPU-light but latency-sensitive; if it runs while Gemma's model load is
    # saturating the core, the first frame is delayed ~20 s and the one-shot
    # fallback can fail on the busy device. Establishing the pipeline now (CPU
    # still free) means captures are fast by the time Gemma is loading.
    try:
        stream.capture()
    except Exception as e:
        print(f"(camera warmup hiccup) {type(e).__name__}: {e}")

    stop_evt = threading.Event()
    nt = threading.Thread(target=_narration_loop, args=(stop_evt, args.narrate_sec),
                          daemon=True)
    nt.start()

    hiccups = 0
    print("narrator - live NPU vision, Gemma narrates every few seconds")
    print(f"web up at http://<board-ip>:{config.WEB_PORT}  ·  Ctrl-C to quit")
    leds.set_color("#6c63ff")  # blue/purple while running
    try:
        while True:
            t0 = time.monotonic()
            try:
                res = stream.detect(min_conf=args.min_conf, max_items=10)
                hiccups = 0
            except Exception as e:
                hiccups += 1
                print(f"(detect hiccup) {type(e).__name__}: {e}")
                if hiccups == 5:
                    print(f"  -> {synap_stream.NPU_WEDGE_HINT}")
                time.sleep(0.3)
                continue
            labels = [d.get("label_en") or d.get("label") for d in res.get("items", [])]
            with _lock:
                _state["labels"] = labels
            webserver.set_photo(res.get("frame", FRAME))
            webserver.broadcast(_payload(res, fps.tick()))
            dt = time.monotonic() - t0
            if dt < interval:
                time.sleep(interval - dt)
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        stop_evt.set()
        leds.set_color("#000000")
        stream.close()


if __name__ == "__main__":
    main()
