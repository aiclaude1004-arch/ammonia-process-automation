"""The drawn routes, checked as geometry rather than taken on trust.

Every defect guarded here was one a reader pointed at in the rendered diagram:
a line crossing a block it has nothing to do with looks connected to it, a stub
that leaves a block and dives back across it leaves a spur poking out from
underneath, and an arrowhead that lands on a curve looks detached.

The routes are produced by scripts/route.js. Re-run it after moving a block or
adding a stream, or these tests will fail on stale geometry.
"""
import json
import math
import unittest
from pathlib import Path

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def load():
    flowsheet = json.loads((CONFIGS / "flowsheet.json").read_text(encoding="utf-8"))
    routes = json.loads((CONFIGS / "stream_routes.json").read_text(encoding="utf-8"))
    return flowsheet, routes


def points_of(d, step=2.0):
    """Sample an SVG path built from M, L and Q commands."""
    out, cur = [], None
    for token in _commands(d):
        kind, nums = token[0], [float(v) for v in token[1:]]
        if kind == "M":
            cur = (nums[0], nums[1])
            out.append(cur)
        elif kind == "L":
            end = (nums[0], nums[1])
            steps = max(1, int(math.dist(cur, end) / step))
            for i in range(1, steps + 1):
                u = i / steps
                out.append((cur[0] + (end[0] - cur[0]) * u,
                            cur[1] + (end[1] - cur[1]) * u))
            cur = end
        else:                                    # quadratic corner easing
            ctrl, end = (nums[0], nums[1]), (nums[2], nums[3])
            for i in range(1, 9):
                u, v = i / 8, 1 - i / 8
                out.append((v * v * cur[0] + 2 * v * u * ctrl[0] + u * u * end[0],
                            v * v * cur[1] + 2 * v * u * ctrl[1] + u * u * end[1]))
            cur = end
    return out


def _commands(d):
    token, out = [], []
    for part in d.replace(",", " ").split():
        if part[0].isalpha():
            if token:
                out.append(token)
            token = [part[0]] + ([part[1:]] if len(part) > 1 else [])
        else:
            token.append(part)
    if token:
        out.append(token)
    return out


class StreamRoutes(unittest.TestCase):
    def setUp(self):
        self.fs, self.routes = load()
        c = self.fs["canvas"]
        self.bw, self.bh = c["block_width"], c["block_height"]
        self.w, self.h = c["width"], c["height"]

    def test_there_is_one_route_for_every_stream(self):
        self.assertEqual(len(self.routes), len(self.fs["streams"]),
                         "stream_routes.json is stale: run `node scripts/route.js`")

    def test_no_route_passes_through_a_block(self):
        """Including its own source and target: that spur is the same defect."""
        offenders = []
        for stream, d in zip(self.fs["streams"], self.routes):
            for q in points_of(d):
                for b in self.fs["blocks"]:
                    if (b["x"] + 2 < q[0] < b["x"] + self.bw - 2 and
                            b["y"] + 2 < q[1] < b["y"] + self.bh - 2):
                        offenders.append(
                            f"{stream['from']}->{stream['to']} through {b['id']}")
                        break
                else:
                    continue
                break
        self.assertEqual(offenders, [])

    def test_no_route_leaves_the_canvas(self):
        for stream, d in zip(self.fs["streams"], self.routes):
            for x, y in points_of(d):
                self.assertTrue(0 <= x <= self.w and 0 <= y <= self.h,
                                f"{stream['from']}->{stream['to']} leaves the sheet")

    def test_every_arrowhead_is_square_to_the_block_it_enters(self):
        """A head at an angle reads as detached from the face it points at."""
        for stream, d in zip(self.fs["streams"], self.routes):
            pts = points_of(d)
            dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
            angle = round(math.degrees(math.atan2(dy, dx)))
            self.assertIn(angle, (0, 90, -90, 180),
                          f"{stream['from']}->{stream['to']} arrives at {angle} degrees")

    def test_no_two_arrowheads_land_on_the_same_point(self):
        heads = [tuple(round(v) for v in points_of(d)[-1]) for d in self.routes]
        self.assertEqual(len(heads), len(set(heads)))

    def test_no_two_routes_are_drawn_on_top_of_each_other(self):
        """A long shared run hides one of the two streams completely.

        Streams converging on the same block are allowed a longer shared
        approach: that is how a manifold is drawn, and it reads correctly.
        Streams with nothing in common must not share a run, because there the
        overlap is pure loss. The longest such run today is 60 px, between
        REFORMER->MEMB and COND->SOFC.
        """
        runs = [(f"{s['from']}->{s['to']}", _runs(d))
                for s, d in zip(self.fs["streams"], self.routes)]
        together = _co_active_pairs()
        for i, (name_a, a_runs) in enumerate(runs):
            for j, (name_b, b_runs) in enumerate(runs[i + 1:], start=i + 1):
                shared = set(name_a.split("->")) & set(name_b.split("->"))
                # Two streams into one unit that never exist in the same case -
                # the exhaust of alternative stacks - are one manifold: a case
                # view draws only one of them, so nothing is hidden.
                if shared and (i, j) not in together:
                    continue
                limit = 140 if shared else 70
                for a in a_runs:
                    for b in b_runs:
                        if a[0] != b[0] or abs(a[1] - b[1]) >= 3.5:
                            continue
                        over = min(a[3], b[3]) - max(a[2], b[2])
                        self.assertLess(over, limit,
                                        f"{name_a} and {name_b} overlap by {over:.0f} px")


def _co_active_pairs():
    """Index pairs of streams that are both active in at least one case."""
    import sys
    sys.path.insert(0, str(CONFIGS.parent / "src"))
    from ammonia_optimizer.flowsheet import load_flowsheet
    from ammonia_optimizer.superstructure import load_superstructure
    superstructure = load_superstructure(CONFIGS / "superstructure.json")
    flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", superstructure)
    pairs = set()
    for run in superstructure.expand_cases():
        live = [k for k, s in enumerate(flowsheet.streams) if s.is_active(run.selection)]
        pairs.update((a, b) for n, a in enumerate(live) for b in live[n + 1:])
    return pairs


def _runs(d):
    """Axis-aligned straight runs as (horizontal?, at, lo, hi)."""
    out, pts = [], []
    for token in _commands(d):
        nums = [float(v) for v in token[1:]]
        pts.append((nums[-2], nums[-1]))
    for a, b in zip(pts, pts[1:]):
        if abs(a[1] - b[1]) < 1 and abs(a[0] - b[0]) > 6:
            out.append((True, a[1], min(a[0], b[0]), max(a[0], b[0])))
        elif abs(a[0] - b[0]) < 1 and abs(a[1] - b[1]) > 6:
            out.append((False, a[0], min(a[1], b[1]), max(a[1], b[1])))
    return out


if __name__ == "__main__":
    unittest.main()
