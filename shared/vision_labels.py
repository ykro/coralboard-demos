"""Vision -> text labels and object boxes.

Gemma 3 270M is text-only, so the camera frame is processed by the NPU first and
the result (labels, or detected objects + boxes) is passed to Gemma as text.

Two NPU paths (both preinstalled SyNAP models, no torch/transformers):
  - scene_labels()   -> `synap_cli_ic`  image classification (mobilenetv2, ImageNet).
  - object_detect()  -> `synap_cli_od`  COCO object detection (80 classes + boxes).

Backends:
  - MOCK         -> synthetic labels / a moving synthetic detection (laptop, no camera).
  - SyNAP (NPU) -> shells out to the SyNAP CLIs on the Coralboard's NPU.
"""

import json
import math
import os
import re
import shutil
import subprocess

from . import config

# --- mock label cycles -----------------------------------------------------
_MOCK_SCENES = [
    ["a coffee cup", "steam", "wood"],
    ["una planta", "luz de ventana", "sombra"],
    ["un teclado", "manos", "pantalla"],
    ["el cielo", "nubes", "un ave"],
]
_scene_i = 0

# --- SyNAP (NPU) -----------------------------------------------------------
SYNAP_IC = os.environ.get(
    "CORAL_SYNAP_IC",
    "/usr/share/synap/models/image_classification/mobilenetv2/npu/model.synap",
)
_synap_labels_cache = {}


def _synap_available(model):
    return bool(shutil.which("synap_cli_ic")) and os.path.exists(model)


def _synap_labels(model):
    if model not in _synap_labels_cache:
        info = os.environ.get("CORAL_SYNAP_LABELS") or os.path.join(
            os.path.dirname(os.path.dirname(model)), "info.json")
        with open(info) as f:
            _synap_labels_cache[model] = json.load(f)["labels"]
    return _synap_labels_cache[model]


def _synap_classify(model, image_path, topn):
    out = subprocess.run(
        ["synap_cli_ic", "-m", model, "--top", str(topn), image_path],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    labels = _synap_labels(model)
    return [labels[it["class_index"]].split(",")[0].strip() for it in data["items"]]


def scene_labels(image_path: str):
    if config.MOCK:
        global _scene_i
        labels = _MOCK_SCENES[_scene_i % len(_MOCK_SCENES)]
        _scene_i += 1
        return labels
    if _synap_available(SYNAP_IC):
        return _synap_classify(SYNAP_IC, image_path, 3) # NPU
    raise RuntimeError(
        "No NPU classifier (synap_cli_ic) found. Run on the Coralboard, or use --mock."
    )


# --- Object detection (COCO) on the NPU ------------------------------------
# `synap_cli_od` returns items[] with class_index, confidence and a
# bounding_box{origin{x,y},size{x,y}} in PIXELS of the input image. We normalize
# the box to [0,1] so the web controller is resolution-independent.
SYNAP_OD = os.environ.get(
    "CORAL_SYNAP_OD",
    "/usr/share/synap/models/object_detection/coco/npu/model.synap",
)

def _od_labels(model):
    """COCO label list from the model dir's info.json (cached)."""
    return _synap_labels(model)  # same info.json -> ["labels"] shape


def _od_available(model):
    return bool(shutil.which("synap_cli_od")) and os.path.exists(model)


_DIMS_RE = re.compile(r"w\s*=\s*(\d+),\s*h\s*=\s*(\d+)")


def _synap_detect(model, image_path, min_conf, max_items):
    # synap_cli_od's OWN score threshold defaults to 0.5 - it drops everything
    # below that BEFORE we ever see it, so real objects at 0.3-0.5 (common indoors
    # / in modest light) silently never appear. Pass our own min_conf through so
    # the CLI keeps them and our Python filter below makes the final call.
    out = subprocess.run(
        ["synap_cli_od", "-m", model, "--score-threshold", str(min_conf), image_path],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    m = _DIMS_RE.search(out)
    iw, ih = (int(m.group(1)), int(m.group(2))) if m else (1, 1)
    labels = _od_labels(model)
    dets = []
    for it in data.get("items", []):
        conf = it.get("confidence", 0.0)
        if conf < min_conf:
            continue
        bb = it["bounding_box"]
        ox, oy = bb["origin"]["x"], bb["origin"]["y"]
        sw, sh = bb["size"]["x"], bb["size"]["y"]
        idx = it["class_index"]
        en = labels[idx] if 0 <= idx < len(labels) else str(idx)
        dets.append({
            "class_index": idx, "label_en": en, "label": en,
            "confidence": round(conf, 3),
            "box": {"x": ox / iw, "y": oy / ih, "w": sw / iw, "h": sh / ih},
            "cx": (ox + sw / 2) / iw, "cy": (oy + sh / 2) / ih,
            "w": sw / iw, "h": sh / ih,
        })
    dets.sort(key=lambda d: d["confidence"], reverse=True)
    return dets[:max_items]


# --- mock moving detection (laptop, no camera) -----------------------------
# Produces a single object whose center glides along a Lissajous path so the
# real-time controller (P1) is alive, and whose label slowly cycles so the
# matching demo (P5) sometimes hits the spoken challenge.
_od_i = 0
_MOCK_OD_LABELS = ["cup", "bottle", "cell phone", "book", "mouse", "banana"]


def object_detect(image_path: str, min_conf: float = 0.35, max_items: int = 10):
    """Detect COCO objects on the NPU. Returns a list of dicts sorted by
    confidence: {class_index, label_en, label(es), confidence, box{x,y,w,h},
    cx, cy, w, h} with all coordinates normalized to [0,1]."""
    if config.MOCK:
        global _od_i
        t = _od_i * 0.20
        _od_i += 1
        cx = 0.5 + 0.32 * math.sin(t)
        cy = 0.5 + 0.24 * math.sin(t * 1.7 + 0.6)
        w = 0.22 + 0.05 * math.sin(t * 0.5)
        h = 0.26 + 0.05 * math.cos(t * 0.4)
        en = _MOCK_OD_LABELS[(_od_i // 12) % len(_MOCK_OD_LABELS)]
        return [{
            "class_index": -1, "label_en": en, "label": en,
            "confidence": 0.9,
            "box": {"x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h},
            "cx": cx, "cy": cy, "w": w, "h": h,
        }]
    if _od_available(SYNAP_OD):
        return _synap_detect(SYNAP_OD, image_path, min_conf, max_items) # NPU
    raise RuntimeError(
        "No NPU detector (synap_cli_od) found. Run on the Coralboard, or use --mock."
    )


# --- Top-k classification with confidences + NPU timing (npu_live demo) -----
# synap_cli_ic prints e.g.:
#   Classification time: 65.55 ms (pre:31.98, inf:33.47, post:0.09)
#   { "items": [ {"class_index": 916, "confidence": 0.80}, ... ], "success": true }
# We return the top-k {label, confidence} AND the parsed timing so the demo can
# show the real NPU inference time (inf) and a measured fps.
_TIMING_RE = re.compile(
    r"Classification time:\s*([\d.]+)\s*ms\s*\(pre:([\d.]+),\s*inf:([\d.]+),\s*post:([\d.]+)\)"
)

# Mock top-k: a few ImageNet-ish classes whose confidences drift so the bars and
# the fps/latency readout look alive on a laptop with no camera.
_MOCK_TOPK = ["coffee mug", "notebook", "water bottle", "desk", "ballpoint pen",
              "computer keyboard", "cellular telephone", "banana", "remote control"]
_topk_i = 0


def classify_topk(image_path: str, k: int = 5):
    """Return {"items": [{"label","confidence","class_index"}], "timing": {...}}.
    timing has total/pre/inf/post in ms (inf = pure NPU compute)."""
    if config.MOCK:
        global _topk_i
        _topk_i += 1
        t = _topk_i * 0.25
        items = []
        for j in range(k):
            label = _MOCK_TOPK[(_topk_i // 7 + j) % len(_MOCK_TOPK)]
            conf = max(0.05, (0.9 - 0.13 * j) * (0.85 + 0.15 * math.sin(t + j)))
            items.append({"label": label, "confidence": round(conf, 3), "class_index": -1})
        items.sort(key=lambda it: it["confidence"], reverse=True)
        inf = 33.0 + 4.0 * math.sin(t)            # plausible NPU inference jitter
        return {"items": items, "timing": {"total": round(inf + 32, 2), "pre": 32.0,
                                           "inf": round(inf, 2), "post": 0.1}}
    if _synap_available(SYNAP_IC):
        out = subprocess.run(
            ["synap_cli_ic", "-m", SYNAP_IC, "--top", str(k), image_path],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out[out.index("{"):out.rindex("}") + 1])
        labels = _synap_labels(SYNAP_IC)
        items = []
        for it in data.get("items", []):
            idx = it["class_index"]
            name = labels[idx].split(",")[0].strip() if 0 <= idx < len(labels) else str(idx)
            items.append({"label": name, "confidence": round(it.get("confidence", 0.0), 3),
                          "class_index": idx})
        m = _TIMING_RE.search(out)
        timing = ({"total": float(m.group(1)), "pre": float(m.group(2)),
                   "inf": float(m.group(3)), "post": float(m.group(4))}
                  if m else {"total": 0.0, "pre": 0.0, "inf": 0.0, "post": 0.0})
        return {"items": items, "timing": timing}
    raise RuntimeError(
        "No NPU classifier (synap_cli_ic) found. Run on the Coralboard, or use --mock."
    )
