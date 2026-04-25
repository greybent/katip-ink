# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
recognition/layout.py — stroke layout analysis.

Segments a list of Stroke objects into lines and words using purely
geometric analysis on stroke bounding boxes — no image processing needed.

Pipeline
--------
1. Compute the bounding box of every stroke.
2. Line clustering: group strokes whose vertical extents overlap or are
   within LINE_MERGE_FACTOR * median_stroke_height of each other.
   Sort groups top-to-bottom by their Y centroid.
3. Word boundary detection: within each line, sort strokes left-to-right.
   Insert a word-break wherever the horizontal gap between consecutive
   strokes exceeds WORD_GAP_FACTOR * median_stroke_width for that line.

The result is a list of "lines", each line being a list of "words", each
word being a list of Stroke objects.
"""

from __future__ import annotations

from typing import List, Tuple

# Vertical gap between two strokes (as a fraction of the median stroke
# height) that is still considered the same line.
LINE_MERGE_FACTOR = 0.6

# Horizontal gap between two consecutive strokes (as a fraction of the
# median stroke width in the line) that signals a word boundary.
WORD_GAP_FACTOR = 0.8


# ── Public API ────────────────────────────────────────────────────────────────

def segment(strokes, line_merge_factor=None, word_gap_factor=None) -> List[List[List]]:
    """
    Given a flat list of Stroke objects, return:
        [ line0, line1, ... ]
    where each lineN is:
        [ word0, word1, ... ]
    and each wordN is:
        [ stroke, stroke, ... ]

    Strokes with fewer than 2 points are ignored.
    """
    lmf = line_merge_factor if line_merge_factor is not None else LINE_MERGE_FACTOR
    wgf = word_gap_factor   if word_gap_factor   is not None else WORD_GAP_FACTOR

    valid = [s for s in strokes if len(s.points) >= 2]
    if not valid:
        return []

    boxes = [_bbox(s) for s in valid]

    lines_of_strokes = _cluster_lines(valid, boxes, lmf)
    result = []
    for line_strokes in lines_of_strokes:
        line_boxes = [_bbox(s) for s in line_strokes]
        words = _split_words(line_strokes, line_boxes, wgf)
        result.append(words)
    return result


def build_line_surfaces(strokes, cfg):
    """
    Return a list of (cairo.ImageSurface, x_offset, y_offset) tuples,
    one per detected line, each tightly cropped to that line's strokes.

    Used by the recognition engine to run OCR per-line.
    """
    import cairo
    from ui.canvas import StrokeCanvas  # import here to avoid circular imports

    lmf = getattr(getattr(cfg, "recognition", None), "line_merge_factor", LINE_MERGE_FACTOR)
    wgf = getattr(getattr(cfg, "recognition", None), "word_gap_factor",   WORD_GAP_FACTOR)
    lines = segment(strokes, line_merge_factor=lmf, word_gap_factor=wgf)
    surfaces = []
    PADDING = 20  # px of whitespace around each line crop

    for line_words in lines:
        line_strokes = [s for word in line_words for s in word]
        if not line_strokes:
            continue

        # Bounding box of the whole line
        all_xs = [x for s in line_strokes for x, y, p in s.points]
        all_ys = [y for s in line_strokes for x, y, p in s.points]
        x1 = max(0, int(min(all_xs)) - PADDING)
        y1 = max(0, int(min(all_ys)) - PADDING)
        x2 = int(max(all_xs)) + PADDING
        y2 = int(max(all_ys)) + PADDING
        w = max(x2 - x1, 1)
        h = max(y2 - y1, 1)

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # Translate so strokes render into the cropped surface
        cr.translate(-x1, -y1)
        _render_strokes_to_context(cr, line_strokes, cfg)
        surface.flush()
        surfaces.append((surface, x1, y1))

    return surfaces


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _bbox(stroke) -> Tuple[float, float, float, float]:
    """Return (x1, y1, x2, y2) bounding box of a stroke."""
    xs = [p[0] for p in stroke.points]
    ys = [p[1] for p in stroke.points]
    return (min(xs), min(ys), max(xs), max(ys))


def _y_center(box) -> float:
    return (box[1] + box[3]) * 0.5


def _height(box) -> float:
    return max(box[3] - box[1], 1.0)


def _width(box) -> float:
    return max(box[2] - box[0], 1.0)


# ── Line clustering ───────────────────────────────────────────────────────────

def _cluster_lines(strokes, boxes, merge_factor=LINE_MERGE_FACTOR):
    """
    Group strokes into lines by merging overlapping/nearby Y extents.
    Returns list of stroke lists, sorted top-to-bottom.
    """
    if not strokes:
        return []

    heights = sorted([_height(b) for b in boxes])
    median_h = heights[len(heights) // 2]
    merge_gap = median_h * merge_factor

    # Sort strokes by their Y centroid
    paired = sorted(zip(boxes, strokes), key=lambda t: _y_center(t[0]))

    # Greedy merge: add stroke to current group if its Y range overlaps
    # or is within merge_gap of the group's Y range
    groups: List[Tuple[float, float, List]] = []  # (group_y1, group_y2, [strokes])

    for box, stroke in paired:
        sy1, sy2 = box[1], box[3]
        merged = False
        for i, (gy1, gy2, gstrokes) in enumerate(groups):
            # Overlapping or close enough vertically?
            if sy1 <= gy2 + merge_gap and sy2 >= gy1 - merge_gap:
                # Expand group range
                groups[i] = (min(gy1, sy1), max(gy2, sy2), gstrokes)
                gstrokes.append(stroke)
                merged = True
                break
        if not merged:
            groups.append((sy1, sy2, [stroke]))

    # Sort groups top-to-bottom by their vertical midpoint
    groups.sort(key=lambda g: (g[0] + g[1]) * 0.5)
    return [g[2] for g in groups]


# ── Word boundary detection ───────────────────────────────────────────────────

def _split_words(strokes, boxes, gap_factor=WORD_GAP_FACTOR):
    """
    Within a single line, split strokes into words by detecting large
    horizontal gaps.  Returns list of word-lists.
    """
    if not strokes:
        return []

    # Sort left-to-right by stroke x1
    paired = sorted(zip(boxes, strokes), key=lambda t: t[0][0])

    widths = [_width(b) for b, _ in paired]
    median_w = sorted(widths)[len(widths) // 2] if widths else 10.0
    gap_threshold = median_w * gap_factor

    words = []
    current_word = [paired[0][1]]
    prev_x2 = paired[0][0][2]  # x2 of the first stroke

    for box, stroke in paired[1:]:
        gap = box[0] - prev_x2  # horizontal gap between this stroke and previous
        if gap > gap_threshold:
            words.append(current_word)
            current_word = [stroke]
        else:
            current_word.append(stroke)
        prev_x2 = max(prev_x2, box[2])

    words.append(current_word)
    return words


# ── Render helper ─────────────────────────────────────────────────────────────

def _render_strokes_to_context(cr, strokes, cfg):
    """Render a list of strokes into an existing Cairo context."""
    import cairo as _cairo
    from input.pressure import pressure_to_thickness

    cfg_i = cfg.input

    for stroke in strokes:
        pts = stroke.points
        if len(pts) < 2:
            continue

        r, g, b, a = stroke.color
        cr.set_source_rgba(r, g, b, a)
        cr.set_line_cap(_cairo.LINE_CAP_ROUND)
        cr.set_line_join(_cairo.LINE_JOIN_ROUND)
        cr.set_antialias(_cairo.ANTIALIAS_BEST)

        avg_p = sum(p[2] for p in pts) / len(pts)
        cr.set_line_width(pressure_to_thickness(
            avg_p, cfg_i.pressure_curve,
            cfg_i.min_thickness, cfg_i.max_thickness,
        ))

        def mid(a, b):
            return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

        sx, sy = mid(pts[0], pts[1])
        cr.move_to(sx, sy)
        for i in range(1, len(pts) - 1):
            cx, cy = pts[i][0], pts[i][1]
            ex, ey = mid(pts[i], pts[i + 1])
            cr.curve_to(cx, cy, cx, cy, ex, ey)
        cr.line_to(pts[-1][0], pts[-1][1])
        cr.stroke()
