"""Camera capture for the Arducam OV5647 (MIPI CSI).

REAL: grabs a frame via libcamera / GStreamer on the Coralboard.
MOCK: returns a bundled placeholder image (or a generated one) so the pipeline
runs on a laptop.

Returns the path to a JPEG on disk so it can be both shown on the local web
page and fed to the vision model.
"""

import os

from . import config

_PLACEHOLDER = os.path.join(os.path.dirname(__file__), "..", "assets", "placeholder.jpg")


def capture_frame(out_path: str) -> str:
    if config.MOCK:
        return _mock_capture(out_path)
    return _csi_capture(out_path)


# --- Real board path -------------------------------------------------------
# The OV5647 sensor's auto-exposure needs several frames to converge, so a single
# one-shot grab comes out almost black. We keep ONE persistent GStreamer stream
# running (exposure settles once and stays settled) and each capture just copies
# the latest frame -> bright AND fast (no per-frame pipeline startup).
# The OV5647 ISP node defaults to NV16 @ 3840x2160 which S_FMT rejects, so we pin
# explicit raw caps and feed jpegenc directly (a videoconvert element breaks the
# format negotiation, so it is omitted).

_stream = {"proc": None, "dir": None}


def _brighten(path):
    """The OV5647 frames come out dim indoors; lift them (auto-contrast + a
    brightness boost) so the scene is visible. Best-effort: a no-op if PIL is
    missing or the file can't be processed, so capture never crashes."""
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        return
    try:
        gain = float(os.environ.get("CORAL_CAM_BRIGHTEN", "1.5"))
        im = Image.open(path).convert("RGB")
        im = ImageOps.autocontrast(im, cutoff=1)
        im = ImageEnhance.Brightness(im).enhance(gain)
        im.save(path, "JPEG", quality=85)
    except Exception:
        pass


def _gst_caps():
    return (os.environ.get("CORAL_CAM_DEV", "/dev/video0"),
            os.environ.get("CORAL_CAM_W", "640"),
            os.environ.get("CORAL_CAM_H", "480"))


def _stop_stream():
    import contextlib
    p = _stream.get("proc")
    if p and p.poll() is None:
        p.terminate()
        with contextlib.suppress(Exception):
            p.wait(timeout=1)
        if p.poll() is None:
            p.kill()
    _stream["proc"] = None


def _start_stream():
    """Launch a persistent capture pipeline that keeps writing the latest JPEG
    frames to a temp dir (keeping only the last few), then wait for the sensor's
    auto-exposure to settle so the first served frame isn't dark."""
    import atexit
    import glob
    import subprocess
    import tempfile
    import time

    dev, w, h = _gst_caps()
    d = os.path.join(tempfile.gettempdir(), "coral_cam")
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(os.path.join(d, "f_*.jpg")):
        try:
            os.remove(f)
        except OSError:
            pass
    proc = subprocess.Popen(
        ["gst-launch-1.0", "-q", "v4l2src", f"device={dev}",
         "!", f"video/x-raw,width={w},height={h}", "!", "jpegenc", "!",
         "multifilesink", f"location={os.path.join(d, 'f_%06d.jpg')}",
         "max-files=4", "post-messages=false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _stream["proc"] = proc
    _stream["dir"] = d
    atexit.register(_stop_stream)
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if len(glob.glob(os.path.join(d, "f_*.jpg"))) >= 4:
            time.sleep(0.4)   # a little extra for exposure to converge
            break
        time.sleep(0.05)


def _csi_capture(out_path: str) -> str:
    """Capture from the OV5647 over CSI. Uses a persistent GStreamer stream so
    auto-exposure stays settled and each frame is bright; falls back to Pi tools
    or a one-shot grab if streaming is unavailable."""
    import glob
    import shutil
    import subprocess

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # Pi-style tools (present on some images)
    for tool in ("rpicam-jpeg", "libcamera-jpeg"):
        if shutil.which(tool):
            subprocess.run(
                [tool, "-n", "-t", "800", "--width", "1024", "--height", "768", "-o", out_path],
                check=True,
            )
            return out_path

    if shutil.which("gst-launch-1.0"):
        dev, w, h = _gst_caps()
        proc = _stream.get("proc")
        if proc is None or proc.poll() is not None:
            _start_stream()
        d = _stream.get("dir")
        files = sorted(glob.glob(os.path.join(d, "f_*.jpg"))) if d else []
        # second-newest is guaranteed fully written (the newest may be mid-flush)
        src = files[-2] if len(files) >= 2 else (files[-1] if files else None)
        if src:
            try:
                shutil.copyfile(src, out_path)
                _brighten(out_path)
                return out_path
            except OSError:
                pass
        # fallback: one-shot grab (darker, but never empty)
        subprocess.run(
            ["gst-launch-1.0", "-q", "-e", "v4l2src", f"device={dev}", "num-buffers=1",
             "!", f"video/x-raw,width={w},height={h}", "!", "jpegenc", "!", "filesink",
             f"location={out_path}"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _brighten(out_path)
        return out_path

    raise RuntimeError(
        "No CSI capture tool found (rpicam-jpeg / libcamera-jpeg / gst-launch-1.0). "
        "Run with --mock, or adjust shared/camera.py to your board's camera stack."
    )


# --- Mock path -------------------------------------------------------------

_mock_i = 0


def _mock_capture(out_path: str) -> str:
    """Write a pleasant gradient placeholder JPEG (there is no camera on a laptop),
    varying each call so the demo/screenshots look alive."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if os.path.exists(_PLACEHOLDER):
        import shutil

        shutil.copyfile(_PLACEHOLDER, out_path)
        return out_path
    try:
        from PIL import Image

        global _mock_i
        palettes = [((108, 99, 255), (236, 180, 220)), ((78, 195, 242), (180, 240, 210)),
                    ((242, 138, 110), (250, 210, 150)), ((110, 200, 150), (230, 240, 160))]
        top, bot = palettes[_mock_i % len(palettes)]
        _mock_i += 1
        w, h = 800, 600
        col = Image.new("RGB", (1, h))
        cpx = col.load()
        for y in range(h):
            t = y / h
            cpx[0, y] = (int(top[0] + (bot[0] - top[0]) * t),
                         int(top[1] + (bot[1] - top[1]) * t),
                         int(top[2] + (bot[2] - top[2]) * t))
        col.resize((w, h)).save(out_path, "JPEG", quality=85)
        return out_path
    except Exception:
        pass
    # Fallback: minimal valid JPEG (gray) if PIL is unavailable.
    gray_jpeg = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c"
        "2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4"
        "001f0000010501010101010100000000000000000102030405060708090a0bffc400b5"
        "10000201030302040305050404000001"
        "7d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433"
        "62728209a1b1c109233352f0156272d10a162434e125f11718191a262728292a353637"
        "38393a434445464748494a535455565758595a636465666768696a737475767778797a"
        "838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9ba"
        "c2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7"
        "f8f9faffda0008010100003f00fbfeffd9"
    )
    with open(out_path, "wb") as f:
        f.write(gray_jpeg)
    return out_path
