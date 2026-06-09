"""Live-frame NPU vision for the showcase demos (reflex / tripwire / narrator).

One seam so the three live demos don't each re-implement "grab a frame, run the
NPU, parse the result." It captures a frame and runs SyNAP inference, returning
parsed results plus the JPEG path to show on the web page.

Three execution layers, picked automatically:

  1. MOCK (laptop, `--mock`) -> synthetic results from `shared.vision_labels`
     (no camera, no NPU). Lets every demo be developed and screenshotted on a
     laptop, exactly like `hello_world`.

  2. SHELL-OUT (default on the board) -> `shared.camera.capture_frame` +
     `shared.vision_labels.classify_topk` / `object_detect`, which shell out to
     the preinstalled `synap_cli_ic` / `synap_cli_od`. PROVEN PATH (it's what
     hello_world uses). Its only cost is that the CLI reloads the model on every
     call, capping throughput at ~4-5 fps.

  3. RESIDENT (opt-in: CORAL_SYNAP_RESIDENT=1) -> a long-lived GStreamer pipeline
     that keeps the model resident on the NPU
     (`v4l2src -> synapimageproc -> synapinfer(model, output=json) -> appsink`),
     which docs/demos-plan.md measured at classify ~31 ms (~32 fps) / detect
     ~271 ms (~3.7 fps). This is the real win, but the exact
     `synapimageproc -> synapinfer` caps are the project's "one real unknown"
     (no example pipelines ship on the board) and need bring-up ON the board.
     Until that's verified it is OFF by default and, if it fails to negotiate at
     start, this module logs the reason and transparently falls back to layer 2,
     so the demos always run. See `_ResidentPipeline` below for the bring-up TODO.

Public API:
    stream = VisionStream(frame_path)
    r = stream.classify(k=5)   # {"items":[{label,confidence,...}], "timing":{inf,...}, "frame": path}
    r = stream.detect(min_conf=0.35, max_items=10)  # {"items":[det,...], "frame": path}
    stream.close()             # release the camera / pipeline
Each call refreshes the frame (so `frame` is current) unless reuse_frame=True.
"""

import os
import time

from . import camera, config, vision_labels

RESIDENT = os.environ.get("CORAL_SYNAP_RESIDENT", "0") == "1"

# Printed by a demo loop after several consecutive inference failures, so a
# beginner staring at a scroll of "(hiccup)" lines learns the likely cause + fix
# instead of nothing. A wedged NPU is usually the aftermath of a kill -9 of a
# synap_cli_* process mid-inference (see HARDWARE.md).
NPU_WEDGE_HINT = (
    "NPU looks wedged (commonly after a kill -9 of synap_cli mid-inference). Stop this demo "
    "and clear it: pkill -f synap_cli; pkill -f run_board, then run again."
)


class VisionStream:
    def __init__(self, frame_path: str):
        self.frame_path = frame_path
        self._resident = None
        self._resident_tried = False

    # --- frame ------------------------------------------------------------
    def capture(self) -> str:
        """Refresh the JPEG frame on disk and return its path. In mock this is a
        generated placeholder; on the board it's the live camera frame."""
        return camera.capture_frame(self.frame_path)

    # --- classification (reflex, narrator) --------------------------------
    def classify(self, k: int = 5, reuse_frame: bool = False) -> dict:
        if not reuse_frame:
            self.capture()
        res = self._resident_classify(k)
        if res is not None:
            res["frame"] = self.frame_path
            return res
        res = vision_labels.classify_topk(self.frame_path, k=k)  # mock or shell-out
        res["frame"] = self.frame_path
        return res

    # --- detection (tripwire, narrator) -----------------------------------
    def detect(self, min_conf: float = 0.35, max_items: int = 10,
               reuse_frame: bool = False) -> dict:
        if not reuse_frame:
            self.capture()
        items = self._resident_detect(min_conf, max_items)
        if items is None:
            items = vision_labels.object_detect(self.frame_path, min_conf=min_conf,
                                                max_items=max_items)  # mock or shell-out
        return {"items": items, "frame": self.frame_path}

    def close(self):
        if self._resident is not None:
            try:
                self._resident.close()
            except Exception:
                pass
            self._resident = None
        camera.release()

    # --- resident pipeline (opt-in, board-only, best-effort) --------------
    def _ensure_resident(self):
        """Bring up the resident GStreamer pipeline once. Returns it, or None if
        disabled / mock / unavailable (caller then uses the shell-out path)."""
        if config.MOCK or not RESIDENT:
            return None
        if self._resident_tried:
            return self._resident
        self._resident_tried = True
        try:
            self._resident = _ResidentPipeline()
        except Exception as e:
            print(f"(synap_stream) resident pipeline unavailable, using synap_cli "
                  f"shell-out: {type(e).__name__}: {e}")
            self._resident = None
        return self._resident

    def _resident_classify(self, k):
        p = self._ensure_resident()
        return p.classify(k) if p is not None else None

    def _resident_detect(self, min_conf, max_items):
        p = self._ensure_resident()
        return p.detect(min_conf, max_items) if p is not None else None


class _ResidentPipeline:
    """Long-lived `synapinfer` GStreamer pipeline keeping a model resident.

    *** BRING-UP TODO (do this on the board; see docs/demos-plan.md) ***
    Construct, in python-gi, a pipeline equivalent to:

        v4l2src device=/dev/video0 io-mode=2
          ! video/x-raw,width=640,height=480
          ! synapimageproc            # resize/preprocess to the model's input
          ! synapinfer model=<MODEL.synap> mode=<post> output=json
          ! appsink name=out

    pull each sample from `appsink`, decode the JSON `synapinfer` attaches, and
    normalize it into the same dicts `shared.vision_labels` returns. The smoke
    test showed `synapinfer` loads the model and negotiates RGB caps but needs
    `synapimageproc` upstream, and no example pipeline ships on the board -- so
    the exact caps between the two elements are the thing to discover here.

    Until that's done this raises, so VisionStream cleanly falls back to the
    proven per-frame `synap_cli_*` shell-out. Constructing it is gated behind
    CORAL_SYNAP_RESIDENT=1 so we never ship an unverified path as the default.
    """

    def __init__(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401  (import proves gi is present)
        raise NotImplementedError(
            "resident synapinfer pipeline not yet brought up on the board "
            "(synapimageproc->synapinfer caps unresolved). Run without "
            "CORAL_SYNAP_RESIDENT to use the synap_cli shell-out path."
        )

    def classify(self, k):
        raise NotImplementedError

    def detect(self, min_conf, max_items):
        raise NotImplementedError

    def close(self):
        pass


# --- small helpers shared by the demos ------------------------------------

class Fps:
    """Exponential-moving-average frames/sec from successive tick() calls."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self.fps = 0.0
        self._last = None

    def tick(self) -> float:
        now = time.monotonic()
        if self._last is not None:
            dt = now - self._last
            if dt > 0:
                inst = 1.0 / dt
                self.fps = inst if self.fps == 0 else (
                    self.alpha * inst + (1 - self.alpha) * self.fps)
        self._last = now
        return self.fps
