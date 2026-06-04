"""Camera capture for the OV5647 (MIPI CSI) on the Coralboard.

REAL (board): a persistent GStreamer pipeline (python-gi) keeps the sensor
streaming and each capture pulls the latest JPEG frame. This matters on this
board's ISP: a fresh one-shot grab cold-starts the sensor (slow, dark, and on
this ISP the `multifilesink`/streaming sinks deliver nothing), while a single
long-lived `appsink` pipeline delivers valid frames continuously (~9 fps) with
the sensor's auto-exposure kept warm. A one-shot `gst-launch` is the fallback.

MOCK (laptop): a generated gradient placeholder so the pipeline runs without a
camera.

Returns the path to a JPEG on disk (shown on the web page and fed to the NPU).

Requires `python3-gi` + `gstreamer1.0-plugins-good` on the board for the fast
path; `setup_board.sh` builds the venv with `--system-site-packages` so the
system `gi` is visible.
"""

import os

from . import config

_PLACEHOLDER = os.path.join(os.path.dirname(__file__), "..", "assets", "placeholder.jpg")


def capture_frame(out_path: str) -> str:
    if config.MOCK:
        return _mock_capture(out_path)
    return _csi_capture(out_path)


# --- Real board path: persistent GStreamer appsink -------------------------

def _gst_caps():
    return (os.environ.get("CORAL_CAM_DEV", "/dev/video0"),
            os.environ.get("CORAL_CAM_W", "640"),
            os.environ.get("CORAL_CAM_H", "480"))


_stream = {"pipeline": None, "sink": None, "Gst": None}


def _brighten(path):
    """The OV5647 underexposes indoor scenes (its auto-exposure meters on bright
    light sources and leaves the rest dark). Lift the shadows with a gamma curve
    (which, unlike auto-contrast, isn't defeated by a bright lamp pinning the
    white point) plus a small brightness gain. Best-effort: a no-op if PIL is
    missing or the file can't be processed, so capture never crashes.
    Tune with CORAL_CAM_GAMMA (lower = brighter shadows, default 0.45) and
    CORAL_CAM_BRIGHTEN (linear gain, default 1.3). Set both to 1 to disable."""
    gamma = float(os.environ.get("CORAL_CAM_GAMMA", "0.45"))
    gain = float(os.environ.get("CORAL_CAM_BRIGHTEN", "1.3"))
    if gamma >= 1.0 and gain == 1.0:
        return
    try:
        from PIL import Image, ImageEnhance
        im = Image.open(path).convert("RGB")
        if 0 < gamma < 1.0:
            lut = [min(255, int((i / 255.0) ** gamma * 255 + 0.5)) for i in range(256)]
            im = im.point(lut * 3)           # apply the curve to R, G and B
        if gain != 1.0:
            im = ImageEnhance.Brightness(im).enhance(gain)
        im.save(path, "JPEG", quality=85)
    except Exception:
        pass


def _start_stream():
    """Start one long-lived appsink pipeline and let it warm up (the sensor's
    auto-exposure settles over the first frames). Returns the appsink, or None
    if python-gi / GStreamer isn't available (caller falls back to a one-shot)."""
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    dev, w, h = _gst_caps()
    pipeline = Gst.parse_launch(
        f"v4l2src device={dev} io-mode=2 ! video/x-raw,width={w},height={h} "
        f"! jpegenc ! appsink name=s max-buffers=3 drop=true sync=false"
    )
    sink = pipeline.get_by_name("s")
    pipeline.set_state(Gst.State.PLAYING)
    pipeline.get_state(Gst.SECOND * 5)          # block until PLAYING (or timeout)
    for _ in range(8):                          # discard warmup frames (AE settling)
        sink.emit("try-pull-sample", Gst.SECOND)

    import atexit
    atexit.register(lambda: pipeline.set_state(Gst.State.NULL))
    _stream.update(pipeline=pipeline, sink=sink, Gst=Gst)
    return sink


def release():
    """Stop the persistent stream and free /dev/video0. Safe to call anytime;
    a no-op if no stream is running. Call this on shutdown so a killed demo
    doesn't leave the camera held (a stuck holder breaks later captures)."""
    p = _stream.get("pipeline")
    Gst = _stream.get("Gst")
    if p is not None and Gst is not None:
        try:
            p.set_state(Gst.State.NULL)
        except Exception:
            pass
    _stream.update(pipeline=None, sink=None)


def _pull_frame(out_path):
    """Pull the latest frame from the persistent stream. Returns True on success."""
    try:
        if _stream["sink"] is None:
            if _start_stream() is None:
                return False
        Gst, sink = _stream["Gst"], _stream["sink"]
        smp = sink.emit("try-pull-sample", Gst.SECOND * 2)
        if not smp:
            return False
        buf = smp.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return False
        try:
            data = bytes(info.data)
        finally:
            buf.unmap(info)
        if len(data) < 1000 or data[:2] != b"\xff\xd8":
            return False
        with open(out_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def _oneshot(out_path):
    """Fallback: a single GStreamer grab. Works on this ISP but cold-starts the
    sensor (slower, and dark until AE settles)."""
    import subprocess
    dev, w, h = _gst_caps()
    subprocess.run(
        ["gst-launch-1.0", "-q", "v4l2src", f"device={dev}", "num-buffers=1",
         "!", f"video/x-raw,width={w},height={h}", "!", "jpegenc", "!",
         "filesink", f"location={out_path}"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out_path


def _csi_capture(out_path: str) -> str:
    import shutil

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if not shutil.which("gst-launch-1.0"):
        raise RuntimeError(
            "No GStreamer found (gst-launch-1.0). Run with --mock, or install "
            "gstreamer1.0-tools + gstreamer1.0-plugins-good on the board."
        )
    if _pull_frame(out_path):       # preferred: persistent appsink stream
        _brighten(out_path)
        return out_path
    _oneshot(out_path)              # fallback: cold one-shot grab
    _brighten(out_path)
    return out_path


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
