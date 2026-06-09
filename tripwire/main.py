"""tripwire - live crossing counter (pure NPU vision).

The NPU detects COCO objects each frame (~3.7 fps); a CPU-side centroid tracker
(shared/tracker.py) gives each one a stable ID between detections and watches it
against a line you draw on the web page. Every time a tracked object crosses the
line the counter ticks (with a per-direction tally). Boxes, the line and the
running count are drawn live.

Every count is driven by a real per-frame NPU detection -- that's the point.
Keep the scene to a few well-separated subjects near the camera: an 80-class
SSD-MobileNet undercounts dense/overlapping/small subjects (docs/demos-plan.md);
it is meant for sparse crossings, not crowd counting.

Laptop (mocked detector, one object on a Lissajous path):  ./run_laptop.sh tripwire
Board (real NPU + camera):                                  ./run_board.sh tripwire
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import cli, config, leds, synap_stream, tracker, webserver

FRAME = os.path.join(os.path.dirname(__file__), "..", "captures", "tripwire.jpg")

# Default line: vertical, down the middle of the frame (normalized [0,1]).
DEFAULT_LINE = ((0.5, 0.05), (0.5, 0.95))


def _payload(res, counter, fps, last_label):
    items = res.get("items", [])
    st = counter.state()
    return {
        "type": "tripwire",
        "boxes": [{"label": d.get("label_en") or d.get("label"),
                   "x": d["box"]["x"], "y": d["box"]["y"],
                   "w": d["box"]["w"], "h": d["box"]["h"],
                   "conf": d["confidence"]} for d in items if "box" in d],
        "count": st["count"], "count_ab": st["count_ab"], "count_ba": st["count_ba"],
        "line": st["line"], "tracks": st["tracks"], "last_event": st["last_event"],
        "fps": round(fps, 1),
        "n_objects": len(items),
        "last_label": last_label,
        "photo": "/photo.jpg",
        "mode": "MOCK" if config.MOCK else "BOARD",
    }


def main():
    parser = argparse.ArgumentParser(description="tripwire - live line-crossing counter (NPU detection)")
    cli.add_common_args(parser)
    parser.add_argument("--min-conf", type=float,
                        default=float(os.environ.get("CORAL_TRIPWIRE_CONF", "0.35")),
                        help="min detection confidence to track")
    args = parser.parse_args()
    cli.apply_common_args(args)

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))
    counter = tracker.LineCounter(DEFAULT_LINE)

    def _on_action(params):
        do = params.get("do")
        if do == "line":      # web page dragged the line -> re-seat it
            try:
                counter.set_line((
                    (float(params["x1"]), float(params["y1"])),
                    (float(params["x2"]), float(params["y2"])),
                ))
            except (KeyError, ValueError):
                return {"ok": False}
        elif do == "reset":   # zero the tally
            counter.reset()
        return {"count": counter.count}
    webserver.set_action_handler(_on_action)

    stream = synap_stream.VisionStream(FRAME)
    fps = synap_stream.Fps()
    last_label = ""
    hiccups = 0
    interval = float(os.environ.get("CORAL_TRIPWIRE_INTERVAL", "0.05"))

    print("tripwire - draw a line on the page; objects crossing it are counted")
    print(f"web up at http://<board-ip>:{config.WEB_PORT}  ·  Ctrl-C to quit")
    leds.set_color("#0000ff")  # armed: blue
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
            events = counter.update(res.get("items", []))
            if events:
                ev = events[-1]
                last_label = ev["label"]
                leds.set_color("#00ff00")    # flash green on a crossing
                print(f"crossing #{counter.count}: {ev['label']} ({ev['dir']})")
            webserver.set_photo(res.get("frame", FRAME))
            webserver.broadcast(_payload(res, counter, fps.tick(), last_label))
            if events:
                time.sleep(0.05)
                leds.set_color("#0000ff")    # back to armed
            dt = time.monotonic() - t0
            if dt < interval:
                time.sleep(interval - dt)
    except KeyboardInterrupt:
        print(f"\nbye - {counter.count} crossings counted")
    finally:
        leds.set_color("#000000")
        stream.close()


if __name__ == "__main__":
    main()
