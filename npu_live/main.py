"""npu_live - watch the Coral NPU run, live.

A continuous classification loop that makes the NPU's speed tangible: every
frame is classified on the NPU (synap_cli_ic) and the web page shows, in real
time, the measured NPU inference latency (ms), the achieved frame rate (fps),
and the top-5 labels with confidence bars that react as you move or occlude an
object in front of the camera.

There is no cloud and no Gemma here - just the camera and the NPU. Unplug the
network and it keeps running. The numbers shown are MEASURED, not assumed: the
latency is parsed straight from the SyNAP runtime and the fps is the real loop
rate.

  camera -> frame -> NPU classify (synap_cli_ic) -> latency + fps + top-5 -> web

Laptop (camera + NPU mocked, UI alive):  ./run_laptop.sh npu
Board (real camera + real NPU):          ./run_board.sh npu
"""

import argparse
import collections
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import camera, cli, config, vision_labels, webserver

FRAME = os.path.join(os.path.dirname(__file__), "..", "captures", "live.jpg")


def main():
    parser = argparse.ArgumentParser(description="Live NPU classification (latency + fps + top-5)")
    cli.add_common_args(parser)
    parser.add_argument("--top", type=int, default=5, help="how many classes to show")
    parser.add_argument("--max-fps", type=float, default=30.0,
                        help="cap the loop rate (keeps the laptop mock realistic; "
                             "the board rarely hits this cap)")
    args = parser.parse_args()
    cli.apply_common_args(args)

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))
    webserver.set_photo(FRAME)
    print(f"npu_live - classifying on the NPU, live  ·  http://<board-ip>:{config.WEB_PORT}")
    print("Ctrl-C to quit\n")

    min_dt = 1.0 / args.max_fps if args.max_fps > 0 else 0.0
    times = collections.deque(maxlen=24)   # loop end-timestamps for rolling fps
    frames = 0
    try:
        while True:
            t0 = time.time()
            camera.capture_frame(FRAME)               # latest frame (fast: persistent stream)
            result = vision_labels.classify_topk(FRAME, k=args.top)
            now = time.time()
            times.append(now)
            fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0
            frames += 1
            inf = result["timing"]["inf"]
            total = result["timing"]["total"]

            webserver.broadcast({
                "type": "npu",
                "items": result["items"],
                "inf_ms": round(inf, 1),
                "total_ms": round(total, 1),
                "fps": round(fps, 1),
                "frames": frames,
                "photo": "/photo.jpg",
                "mode": "MOCK" if config.MOCK else "BOARD",
            })
            if frames % 15 == 0:
                top = result["items"][0] if result["items"] else {"label": "-", "confidence": 0}
                print(f"frame {frames:5d}  inf {inf:5.1f} ms  fps {fps:4.1f}  "
                      f"top: {top['label']} ({top['confidence']*100:.0f}%)")

            dt = time.time() - t0
            if dt < min_dt:
                time.sleep(min_dt - dt)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
