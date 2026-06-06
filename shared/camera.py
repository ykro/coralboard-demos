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
import subprocess

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
    """Light cosmetic pass on top of an already well-exposed frame.

    The heavy lifting now happens IN THE SENSOR: `_configure_sensor()` puts the
    OV5647 into auto-exposure / auto-gain / auto-white-balance, so the captured
    frame is properly bright and neutral with real (low-noise) signal. Previously
    the sensor sat in manual mode at near-minimum gain -> near-black frames, and
    this function tried to rescue them with a big gamma lift + gray-world WB +
    autocontrast, which only amplified the noise floor into coloured 'static'.

    So this is now just a GENTLE gamma to open the shadows a touch; WB / gain /
    contrast / denoise default OFF (the sensor handles colour + exposure, and a
    clean frame needs no denoise). All still available via env for tricky rooms.
    Best-effort: a no-op if PIL is missing so capture never crashes.

    Tune: CORAL_CAM_GAMMA (lower=brighter shadows, default 0.6; >=1 disables),
    CORAL_CAM_BRIGHTEN (extra gain, default 1.0=off), CORAL_CAM_WB (software
    gray-world WB 1/0, default 0 - sensor AWB is on), CORAL_CAM_CONTRAST
    (autocontrast cutoff %, default 0=off), CORAL_CAM_DENOISE (1/0, default 0)."""
    gamma = float(os.environ.get("CORAL_CAM_GAMMA", "0.6"))
    gain = float(os.environ.get("CORAL_CAM_BRIGHTEN", "1.0"))
    wb = os.environ.get("CORAL_CAM_WB", "0") == "1"
    cutoff = float(os.environ.get("CORAL_CAM_CONTRAST", "0"))
    denoise = os.environ.get("CORAL_CAM_DENOISE", "0") == "1"
    if gamma >= 1.0 and gain == 1.0 and not wb and cutoff == 0 and not denoise:
        return
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
        im = Image.open(path).convert("RGB")
        if 0 < gamma < 1.0:
            lut = [min(255, int((i / 255.0) ** gamma * 255 + 0.5)) for i in range(256)]
            im = im.point(lut * 3)           # apply the curve to R, G and B
        if wb:
            r, g, b = ImageStat.Stat(im).mean
            avg = (r + g + b) / 3.0
            sc = [min(max(avg / max(c, 1.0), 0.6), 1.6) for c in (r, g, b)]  # clamp
            ch = [[min(255, int(i * sc[k] + 0.5)) for i in range(256)] for k in range(3)]
            im = im.point(ch[0] + ch[1] + ch[2])
        if gain != 1.0:
            im = ImageEnhance.Brightness(im).enhance(gain)
        if cutoff > 0:
            im = ImageOps.autocontrast(im, cutoff=cutoff)  # robust black/white point
        if denoise:
            # Frame-averaging (see _pull_frame) already kills most noise without
            # blur; here just a soft blur for residual speckle + a mild desaturate
            # for chroma noise. NO sharpen/unsharp - it re-amplifies sensor noise
            # into the coloured static.
            im = im.filter(ImageFilter.GaussianBlur(0.4))
            im = ImageEnhance.Color(im).enhance(0.85)     # tame residual colour speckle
        im.save(path, "JPEG", quality=92)
    except Exception:
        pass


_sensor_subdev = None


def _find_sensor_subdev():
    """The exposure / gain / white-balance controls live on the SENSOR subdev,
    NOT on /dev/video0 (which only exposes `wb_enable`). Find the /dev/v4l-subdev*
    that carries the OV5647's `analogue_gain` control. Cached; override with
    CORAL_CAM_SENSOR_SUBDEV."""
    global _sensor_subdev
    if _sensor_subdev is not None:
        return _sensor_subdev
    env = os.environ.get("CORAL_CAM_SENSOR_SUBDEV")
    if env:
        _sensor_subdev = env
        return env
    import glob
    import shutil
    _sensor_subdev = ""
    if not shutil.which("v4l2-ctl"):
        return ""
    for d in sorted(glob.glob("/dev/v4l-subdev*")):
        try:
            out = subprocess.run(["v4l2-ctl", "-d", d, "--list-ctrls"],
                                 capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if "analogue_gain" in out:
            _sensor_subdev = d
            return d
    return ""


def _configure_sensor():
    """Put the OV5647 into auto exposure / auto gain / auto white-balance so it
    delivers a bright, neutral, low-noise frame in HARDWARE. Without this the
    sensor powers up in manual mode at near-minimum gain -> near-black frames,
    and lifting those in software is what produced the coloured 'static'. Must be
    called after the pipeline is PLAYING (the sensor resets to manual defaults on
    every stream start). Env overrides:
      CORAL_CAM_AE / CORAL_CAM_AGC / CORAL_CAM_AWB (1/0, default 1) - auto
        exposure / gain / white balance.
      CORAL_CAM_GAIN     - manual analogue_gain (16..1023) when AGC=0.
      CORAL_CAM_EXPOSURE - manual exposure when AE=0."""
    dev = _find_sensor_subdev()
    if not dev:
        return
    ae = os.environ.get("CORAL_CAM_AE", "1") == "1"
    agc = os.environ.get("CORAL_CAM_AGC", "1") == "1"
    awb = os.environ.get("CORAL_CAM_AWB", "1") == "1"
    ctrls = [f"auto_exposure={0 if ae else 1}",        # 0=Auto, 1=Manual (V4L2)
             f"gain_automatic={1 if agc else 0}",
             f"white_balance_automatic={1 if awb else 0}"]
    if not agc and os.environ.get("CORAL_CAM_GAIN"):
        ctrls.append("analogue_gain=" + os.environ["CORAL_CAM_GAIN"])
    if not ae and os.environ.get("CORAL_CAM_EXPOSURE"):
        ctrls.append("exposure=" + os.environ["CORAL_CAM_EXPOSURE"])
    try:
        subprocess.run(["v4l2-ctl", "-d", dev, "--set-ctrl", ",".join(ctrls)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def _start_stream():
    """Start one long-lived appsink pipeline, switch the sensor to auto
    exposure/gain/WB, and let auto-exposure settle over the first frames. Returns
    the appsink, or None if python-gi / GStreamer isn't available (caller falls
    back to a one-shot)."""
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    dev, w, h = _gst_caps()
    q = os.environ.get("CORAL_CAM_JPEG_Q", "92")   # high-quality capture (cheap;
    pipeline = Gst.parse_launch(                    # avoids JPEG-block artifacts)
        f"v4l2src device={dev} io-mode=2 ! video/x-raw,width={w},height={h} "
        f"! jpegenc quality={q} ! appsink name=s max-buffers=3 drop=true sync=false"
    )
    sink = pipeline.get_by_name("s")
    pipeline.set_state(Gst.State.PLAYING)
    pipeline.get_state(Gst.SECOND * 5)          # block until PLAYING (or timeout)
    _configure_sensor()                         # auto AE/AGC/AWB on the sensor
    warm = int(os.environ.get("CORAL_CAM_WARMUP", "30"))
    for _ in range(warm):                       # discard frames while AE converges
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


def _pull_bytes():
    """Pull one latest JPEG frame from the persistent stream as bytes (or None)."""
    try:
        if _stream["sink"] is None:
            if _start_stream() is None:
                return None
        Gst, sink = _stream["Gst"], _stream["sink"]
        smp = sink.emit("try-pull-sample", Gst.SECOND * 2)
        if not smp:
            return None
        buf = smp.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            data = bytes(info.data)
        finally:
            buf.unmap(info)
        if len(data) < 1000 or data[:2] != b"\xff\xd8":
            return None
        return data
    except Exception:
        return None


def _average(frames):
    """Running pixel mean of N PIL images. Random sensor noise is uncorrelated
    frame-to-frame, so it averages down ~sqrt(N) while real detail stays put -
    the one denoise that adds no blur. (Image.blend(a,b,1/k) = running mean.)"""
    from PIL import Image
    avg = frames[0]
    for k, f in enumerate(frames[1:], start=2):
        if f.size != avg.size:
            f = f.resize(avg.size)
        avg = Image.blend(avg, f, 1.0 / k)
    return avg


def _pull_frame(out_path):
    """Pull a frame (or a stack of frames, averaged) from the persistent stream.
    CORAL_CAM_STACK frames are averaged to beat down the OV5647's heavy low-light
    noise without the blur/posterisation a spatial denoise causes. Returns True
    on success."""
    data = _pull_bytes()
    if data is None:
        return False
    # Frame-averaging is off by default now the sensor exposes properly (it would
    # only add motion ghosting); set CORAL_CAM_STACK>1 for extra denoise on a
    # static scene in a very dark room.
    n = int(os.environ.get("CORAL_CAM_STACK", "1"))
    if n > 1:
        try:
            import io
            from PIL import Image
            frames = [Image.open(io.BytesIO(data)).convert("RGB")]
            for _ in range(n - 1):
                d = _pull_bytes()
                if d is not None:
                    frames.append(Image.open(io.BytesIO(d)).convert("RGB"))
            if len(frames) > 1:
                _average(frames).save(out_path, "JPEG", quality=95)
                return True
        except Exception:
            pass  # fall through to writing the single raw frame
    with open(out_path, "wb") as f:
        f.write(data)
    return True


def _oneshot(out_path):
    """Fallback: a single GStreamer grab. Works on this ISP but cold-starts the
    sensor (slower, and dark until AE settles)."""
    import subprocess
    dev, w, h = _gst_caps()
    q = os.environ.get("CORAL_CAM_JPEG_Q", "92")
    subprocess.run(
        ["gst-launch-1.0", "-q", "v4l2src", f"device={dev}", "num-buffers=1",
         "!", f"video/x-raw,width={w},height={h}", "!", "jpegenc", f"quality={q}", "!",
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
