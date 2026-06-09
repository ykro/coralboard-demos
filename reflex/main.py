"""reflex - reactive smart-camera (pure NPU vision).

Hold an object up to the camera; the NPU classifies it in ~31 ms, the board
collapses the fine-grained ImageNet label into a coarse category, and the RGB
status LED changes color instantly (food->green, animal->blue, vehicle->red,
device->white, clothing->magenta, other->cyan). The web page shows the live
frame, the big category, the top-1 label + confidence, the top-k bars and the
real NPU inference time.

This closes the camera -> NPU -> physical-action loop at NPU speed, fully
offline, which is the point: the instant LED reaction makes the latency visceral.

Anti-flicker (docs/demos-plan.md): MobileNet's top-1 chatters because many frames
contain more than one object, so the decision is debounced with (a) a majority
vote over the last N frames and (b) a confidence floor to ENTER a new category,
while the current category persists as long as it keeps showing up (a dead band).
The LED only changes when a new category is clearly and repeatedly winning.

Laptop (mocked NPU, drifting labels):   ./run_laptop.sh reflex
Board (real NPU + LED):                  ./run_board.sh reflex
"""

import argparse
import os
import sys
import time
from collections import Counter, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import cli, config, imagenet_buckets, leds, synap_stream, webserver

FRAME = os.path.join(os.path.dirname(__file__), "..", "captures", "reflex.jpg")


class Debouncer:
    """Stabilizes the chattering top-1 into a steady category.

    A new category becomes the displayed/LED category only when it (a) wins a
    majority of the last `window` frames AND (b) its mean confidence over those
    frames clears `enter_conf`. The current category keeps the LED as long as it
    still appears in the window, so a one-frame distractor never flips it -- that
    gap between "needed to enter" and "needed to stay" is the dead band."""

    def __init__(self, window=7, enter_conf=0.45):
        self.window = window
        self.enter_conf = enter_conf
        self.hist = deque(maxlen=window)   # (bucket, confidence)
        self.current = None

    def push(self, bucket, conf):
        self.hist.append((bucket, conf))
        counts = Counter(b for b, _c in self.hist)
        winner, n = counts.most_common(1)[0]
        # mean confidence of the frames that voted for the winner
        confs = [c for b, c in self.hist if b == winner]
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        if self.current is None:
            self.current = winner
        elif winner != self.current and n * 2 > self.window and mean_conf >= self.enter_conf:
            self.current = winner    # clear, repeated, confident winner -> switch
        return self.current


def _payload(res, decided_label, bucket, color, stable_bucket, stable_color, fps):
    items = res.get("items", [])
    timing = res.get("timing", {}) or {}
    top = items[0] if items else {"label": "-", "confidence": 0.0}
    return {
        "type": "reflex",
        "label": top.get("label", "-"),
        "confidence": round(top.get("confidence", 0.0), 3),
        "bucket": bucket, "color": color,
        "stable_bucket": stable_bucket, "stable_color": stable_color,
        "decided_label": decided_label,
        "items": [{"label": it["label"], "confidence": round(it["confidence"], 3)}
                  for it in items],
        "inf_ms": round(timing.get("inf", 0.0), 1),
        "total_ms": round(timing.get("total", 0.0), 1),
        "fps": round(fps, 1),
        "buckets": [{"name": n, "color": c} for n, c in imagenet_buckets.BUCKETS],
        "photo": "/photo.jpg",
        "mode": "MOCK" if config.MOCK else "BOARD",
    }


def main():
    parser = argparse.ArgumentParser(description="reflex - reactive smart-camera (NPU classify -> LED)")
    cli.add_common_args(parser)
    parser.add_argument("--window", type=int, default=int(os.environ.get("CORAL_REFLEX_WINDOW", "7")),
                        help="majority-vote window (frames) for anti-flicker")
    parser.add_argument("--enter-conf", type=float, default=float(os.environ.get("CORAL_REFLEX_ENTER", "0.45")),
                        help="confidence needed to switch to a new category")
    args = parser.parse_args()
    cli.apply_common_args(args)

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))

    def _on_action(params):
        if params.get("do") == "led":        # manual LED override button
            leds.set_color("#" + params.get("color", "ffffff"))
    webserver.set_action_handler(_on_action)

    stream = synap_stream.VisionStream(FRAME)
    fps = synap_stream.Fps()
    debouncer = Debouncer(window=args.window, enter_conf=args.enter_conf)
    last_led = None
    hiccups = 0
    interval = float(os.environ.get("CORAL_REFLEX_INTERVAL", "0.1"))  # aim ~10 Hz UI

    print("reflex - hold an object to the camera; the LED reacts to its category")
    print(f"web up at http://<board-ip>:{config.WEB_PORT}  ·  Ctrl-C to quit")
    leds.set_color("#00ffff")  # idle: cyan (== "other")
    try:
        while True:
            t0 = time.monotonic()
            try:
                res = stream.classify(k=5)
                hiccups = 0
            except Exception as e:
                hiccups += 1
                print(f"(classify hiccup) {type(e).__name__}: {e}")
                if hiccups == 5:
                    print(f"  -> {synap_stream.NPU_WEDGE_HINT}")
                time.sleep(0.3)
                continue
            bucket, color, decided = imagenet_buckets.bucket_for_topk(
                res.get("items", []), min_conf=0.0)
            top_conf = res["items"][0]["confidence"] if res.get("items") else 0.0
            stable = debouncer.push(bucket, top_conf)
            stable_color = imagenet_buckets.BUCKET_COLOR.get(stable, "#00ffff")
            if stable != last_led:
                leds.set_color(stable_color)       # physical reaction
                last_led = stable
            webserver.set_photo(res.get("frame", FRAME))
            webserver.broadcast(_payload(res, decided, bucket, color,
                                         stable, stable_color, fps.tick()))
            dt = time.monotonic() - t0
            if dt < interval:
                time.sleep(interval - dt)
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        leds.set_color("#000000")
        stream.close()


if __name__ == "__main__":
    main()
