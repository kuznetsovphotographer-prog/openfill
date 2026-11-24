# SPDX-License-Identifier: Apache-2.0
# Modified in the PhotoCraft Workflow Tools fork.
"""Optional local workflow choices for Fill and Remove."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CUSTOM_WORKFLOW_ID = "custom-workflow"
PREFIX = CUSTOM_WORKFLOW_ID + ":"
MANIFEST = "local-fill-workflows.json"
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_SELECTED = re.compile(rb"[\x80-\xff]+")
_NONZERO = re.compile(rb"[^\x00]+")
_MAGENTA = bytes((255, 0, 255, 255))


@dataclass(frozen=True)
class FillWorkflow:
    path: Path
    label: str
    inputs: str
    remove_prompt: str = ""
    mark_selection: bool = False


def is_custom_workflow(choice: str | None) -> bool:
    return bool(choice and (choice == CUSTOM_WORKFLOW_ID or choice.startswith(PREFIX)))


def mark_removal_reference(rgba: bytes, mask: bytes) -> bytes:
    """Show an image-edit model where to work, without changing the result's layer mask."""
    if len(rgba) != 4 * len(mask):
        raise ValueError("Image and selection dimensions do not match.")
    runs = _SELECTED if _SELECTED.search(mask) else _NONZERO
    marked = bytearray(rgba)
    for match in runs.finditer(mask):
        begin, end = match.span()
        marked[4 * begin : 4 * end] = _MAGENTA * (end - begin)
    return bytes(marked)


def load(base: Path) -> dict[str, FillWorkflow]:
    """Read only named JSON files in this profile; never fetch or install anything."""
    try:
        raw = json.loads((base / MANIFEST).read_text(encoding="utf-8-sig"))
        base = base.resolve()
    except (OSError, ValueError, RuntimeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    out: dict[str, FillWorkflow] = {}
    labels: set[str] = set()
    for key, row in raw.items():
        if not _ID.fullmatch(key) or not isinstance(row, dict):
            continue
        label, filename, inputs = row.get("label"), row.get("file"), row.get("inputs", "")
        if not isinstance(label, str) or not label.strip() or label.strip() in labels:
            continue
        if not isinstance(filename, str) or not isinstance(inputs, str):
            continue
        filename_path = Path(filename)
        if filename_path.name != filename or filename_path.suffix.lower() != ".json":
            continue
        try:
            path = (base / filename_path).resolve()
            if path.parent != base or not path.is_file():
                continue
        except (OSError, ValueError, RuntimeError):
            continue
        prompt = row.get("remove_prompt", "")
        prompt = prompt.strip() if isinstance(prompt, str) else ""
        out[PREFIX + key] = FillWorkflow(path, label.strip(), inputs, prompt, row.get("mark_selection") is True)
        labels.add(label.strip())
    return out
