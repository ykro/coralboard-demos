"""CPU-side centroid tracking + line-crossing counting for `tripwire`.

The NPU detects COCO objects at ~3.7 fps (detect ~271 ms, per docs/demos-plan.md).
That's enough to count a few subjects crossing a line if a light tracker on the
CPU bridges the gap between detections: it gives each detection a stable ID by
matching it to the nearest previous centroid, ages out the ones that disappear,
and watches each tracked centroid's path against a user-drawn line. A crossing is
counted when the centroid moves from one side of the line to the other.

Everything works in normalized [0,1] image coordinates so it's resolution- and
mock/board-independent. No numpy: a handful of objects per frame, plain Python is
plenty.
"""

import math


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _side(p, a, b):
    """Signed side of point p relative to the directed line a->b (2D cross
    product). >0 one side, <0 the other, 0 on the line."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


class Track:
    __slots__ = ("id", "cx", "cy", "label", "missed", "side", "counted")

    def __init__(self, tid, cx, cy, label, side):
        self.id = tid
        self.cx = cx
        self.cy = cy
        self.label = label
        self.missed = 0
        self.side = side        # last sign relative to the line (-1/0/+1)
        self.counted = False    # already tallied a crossing (debounce re-counts)


class LineCounter:
    """Tracks centroids across frames and counts crossings of a single line.

    line = ((x1, y1), (x2, y2)) in [0,1]. `max_match_dist` is how far a detection
    can be from a track and still be considered the same object (normalized);
    `max_missed` is how many consecutive frames a track can go undetected before
    it's dropped."""

    def __init__(self, line, max_match_dist=0.18, max_missed=8):
        self.a, self.b = line
        self.max_match_dist = max_match_dist
        self.max_missed = max_missed
        self.tracks = {}
        self._next_id = 1
        self.count = 0          # total crossings (either direction)
        self.count_ab = 0       # crossings from the a-side to the b-side
        self.count_ba = 0       # the other way
        self.last_event = None  # {"id", "label", "dir"} of the most recent crossing

    def set_line(self, line):
        self.a, self.b = line
        # Re-seat every track's remembered side against the new line so moving the
        # line doesn't fire a phantom crossing on the next update.
        for t in self.tracks.values():
            t.side = _sign(_side((t.cx, t.cy), self.a, self.b))
            t.counted = False

    def update(self, detections):
        """Feed the current frame's detections (each a dict with cx, cy and a
        label/label_en). Returns the list of crossing events fired THIS frame."""
        dets = [(d.get("cx"), d.get("cy"), d.get("label_en") or d.get("label") or "obj")
                for d in detections if d.get("cx") is not None]

        # Greedy nearest-neighbour match of detections to existing tracks.
        unmatched = set(self.tracks.keys())
        events = []
        used = [False] * len(dets)
        # Match closest pairs first for stability with a few objects.
        pairs = []
        for tid, t in self.tracks.items():
            for i, (cx, cy, _lbl) in enumerate(dets):
                pairs.append((_dist((t.cx, t.cy), (cx, cy)), tid, i))
        pairs.sort(key=lambda p: p[0])
        matched_det = {}
        for dist, tid, i in pairs:
            if dist > self.max_match_dist:
                break
            if tid not in unmatched or used[i]:
                continue
            unmatched.discard(tid)
            used[i] = True
            matched_det[tid] = i

        for tid, i in matched_det.items():
            cx, cy, lbl = dets[i]
            ev = self._advance(self.tracks[tid], cx, cy, lbl)
            if ev:
                events.append(ev)

        # Unmatched existing tracks: age them out.
        for tid in list(unmatched):
            t = self.tracks[tid]
            t.missed += 1
            if t.missed > self.max_missed:
                del self.tracks[tid]

        # New detections with no track: spawn one (no crossing on first sight).
        for i, (cx, cy, lbl) in enumerate(dets):
            if used[i]:
                continue
            side = _sign(_side((cx, cy), self.a, self.b))
            self.tracks[self._next_id] = Track(self._next_id, cx, cy, lbl, side)
            self._next_id += 1

        return events

    def _advance(self, t, cx, cy, lbl):
        t.cx, t.cy, t.label, t.missed = cx, cy, lbl, 0
        new_side = _sign(_side((cx, cy), self.a, self.b))
        ev = None
        if t.side != 0 and new_side != 0 and new_side != t.side:
            direction = "ab" if t.side < 0 else "ba"
            self.count += 1
            if direction == "ab":
                self.count_ab += 1
            else:
                self.count_ba += 1
            ev = {"id": t.id, "label": t.label, "dir": direction}
            self.last_event = ev
        if new_side != 0:
            t.side = new_side
        return ev

    def state(self):
        """Snapshot for the web payload."""
        return {
            "count": self.count, "count_ab": self.count_ab, "count_ba": self.count_ba,
            "tracks": [{"id": t.id, "cx": round(t.cx, 4), "cy": round(t.cy, 4),
                        "label": t.label} for t in self.tracks.values()],
            "line": [list(self.a), list(self.b)],
            "last_event": self.last_event,
        }


def _sign(x, eps=1e-9):
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0
