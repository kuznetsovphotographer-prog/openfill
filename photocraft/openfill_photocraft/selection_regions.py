# SPDX-License-Identifier: Apache-2.0
# Modified in the PhotoCraft Workflow Tools fork.
"""Split an 8-bit selection into connected masks without thresholding its soft edges."""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image

from openfill.geometry import Rect

MAX_AREAS = 32
_MAX_RUNS = 500_000
_SELECTED = re.compile(rb"[\x01-\xff]+")


@dataclass(frozen=True)
class SelectionRegion:
    rect: Rect
    grayscale: Image.Image


def split_selection(selection: Image.Image) -> list[SelectionRegion]:
    """Return just the disconnected areas in reading order; an empty list means no split.

    Segment row runs instead of walking individual pixels in Python. Diagonal
    contact counts as connected; fully deselected holes and original alpha survive.
    """
    box = selection.getbbox()
    if box is None:
        return []
    x0, y0, right, bottom = box
    w, h = right - x0, bottom - y0
    sub = selection.crop(box)
    if sub.getextrema()[0] > 0:
        return []  # solid rectangle, even with a uniform partial selection
    raw = sub.tobytes()
    del sub
    runs: list[tuple[int, int, int]] = []
    parents: list[int] = []

    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    previous = (0, 0)
    for y in range(h):
        start, end = y * w, (y + 1) * w
        current = len(runs)
        j, previous_end = previous
        for match in _SELECTED.finditer(raw, start, end):
            lo, hi = match.start() - start, match.end() - start
            i = len(runs)
            if i >= _MAX_RUNS:
                raise ValueError("This selection is too detailed to split. Select simpler areas.")
            runs.append((y, lo, hi))
            parents.append(i)
            while j < previous_end and runs[j][2] < lo:
                j += 1
            k = j
            while k < previous_end and runs[k][1] <= hi:
                a, b = root(i), root(k)
                if a != b:
                    parents[max(a, b)] = min(a, b)
                k += 1
        previous = (current, len(runs))

    groups: dict[int, list[tuple[int, int, int]]] = {}
    for i, run in enumerate(runs):
        k = root(i)
        if k not in groups:
            if len(groups) == MAX_AREAS:
                raise ValueError(f"Select {MAX_AREAS} separate areas or fewer at a time.")
            groups[k] = []
        groups[k].append(run)
    if len(groups) < 2:
        return []
    out = []
    for parts in groups.values():
        top, end_y = parts[0][0], parts[-1][0] + 1
        left, end_x = min(r[1] for r in parts), max(r[2] for r in parts)
        rw, rh = end_x - left, end_y - top
        pixels = bytearray(rw * rh)
        for y, lo, hi in parts:
            off = (y - top) * rw + lo - left
            pixels[off : off + hi - lo] = raw[y * w + lo : y * w + hi]
        out.append(SelectionRegion(Rect(x0 + left, y0 + top, rw, rh), Image.frombytes("L", (rw, rh), pixels)))
    return out
