# SPDX-License-Identifier: Apache-2.0
# Modified in the PhotoCraft Workflow Tools fork.
"""User-requested memory controls for the local ComfyUI, not an editor command."""

from __future__ import annotations

import time
from urllib.parse import urlsplit

from openfill import png
from openfill.backend import InpaintRequest, Sampling, Txt2ImgRequest
from openfill.comfy_api import ComfyClient
from openfill.named_fill import is_custom_workflow

from .localization import tr


def _local(app, url: str) -> ComfyClient:
    dest = urlsplit(url)
    if (
        app.settings.backend != "comfyui"
        or app.settings.uses_remote
        or dest.hostname not in ("127.0.0.1", "::1", "localhost")
    ):
        raise RuntimeError(tr("vram_local"))
    client = ComfyClient(url, timeout=4)
    q = client.queue()
    if q.get("queue_running") or q.get("queue_pending"):
        raise RuntimeError(tr("queue_busy"))
    return client


def _vram(client):
    rows = client.system_stats().get("devices") or []
    return next((d for d in rows if d.get("type") not in ("cpu", None) and d.get("vram_total")), {})


def _summary(stats: dict) -> str:
    if not stats or "vram_free" not in stats:
        return ""
    return tr("vram_stats", free=stats["vram_free"] / 2**30, total=stats["vram_total"] / 2**30)


def unload(app) -> str:
    if app.settings.backend != "comfyui" or app.settings.uses_remote:
        raise RuntimeError(tr("vram_local"))
    url = app.server.url()
    if not app.server.is_healthy(url):
        return tr("not_running")
    client = _local(app, url)
    before = _vram(client)
    client.release_memory()
    after = before
    for _ in range(8):
        time.sleep(0.25)
        after = _vram(client)
        if after.get("vram_free", 0) > before.get("vram_free", 0) + 32 * 2**20:
            break
    delta = after.get("vram_free", 0) - before.get("vram_free", 0)
    message = tr("released", delta=delta / 2**30) if delta >= 64 * 2**20 else tr("released_same")
    return f"{message} {_summary(after)}".strip()


def preload_choices(app) -> dict[str, str]:
    if app.settings.backend != "comfyui" or app.settings.uses_remote:
        return {}
    out = {}
    for operation in ("fill", "remove", "expand", "txt2img", "bgremove", "upscale"):
        for entry in app.installed_models(operation):
            out.setdefault(entry.id, entry.name.split(" (+", 1)[0].split(" (", 1)[0])
    out.update(app.custom_workflow_choices())
    return out


def preload(app, choice: str, progress, cancel, *, operation="fill") -> str:
    if app.settings.backend != "comfyui" or app.settings.uses_remote:
        raise RuntimeError(tr("vram_local"))
    labels = preload_choices(app)
    if choice == "default" and operation == "remove":
        default = app.removal_model_available()
        choice = default.id if default is not None else app.removal_fallback("active")
        if choice == "active":
            choice = app.active_model_id()
    if choice not in labels:
        raise RuntimeError(tr("pick_model"))
    entry, spec = app.resolve_model(choice, fetch_preview=False)
    if operation == "txt2img" and (entry is None or "txt2img" not in entry.capabilities):
        raise RuntimeError(tr("pick_model"))
    backend = app.backend(progress, cancel)
    client = _local(app, backend.client.base_url)
    # A small private synthetic image runs the exact graph, including loaders and VAE.
    # No document is read, opened, or saved. ComfyUI decides which weights to retain.
    w = h = 384
    sampling = Sampling(steps=2, cfg=30.0 if spec.arch == "flux" else 1.0, seed=17)
    if operation == "txt2img":
        backend.txt2img(Txt2ImgRequest(w, h, "A flat gray square.", "", spec, sampling), progress, None, cancel)
        return _preloaded(app, client, labels[choice])

    image = bytearray((170, 176, 181) * (w * h))
    mask = bytearray(w * h)
    for y in range(160, 224):
        mask[y * w + 160 : y * w + 224] = b"\xff" * 64
    mode = "expand" if operation == "expand" else "fill"
    if spec.background_removal:
        mode = "bgremove"
    elif spec.upscaler:
        mode = "upscale"
    work_w, work_h = app.upscale_size(w, h, 2, spec) if mode == "upscale" else (w, h)
    if mode == "bgremove":
        picture = png.encode(w, h, bytes(image), 3)
        painted = png.encode(w, h, bytes((170, 176, 181, 255)) * (w * h), 4)
    elif is_custom_workflow(choice):
        from openfill.custom_workflow import mask_rgba, rgba_with_mask

        rgba = bytearray(b"\xff" * (4 * w * h))
        for channel in range(3):
            rgba[channel::4] = image[channel::3]
        picture = png.encode(w, h, rgba_with_mask(bytes(rgba), bytes(mask)), 4)
        painted = png.encode(w, h, mask_rgba(bytes(mask)), 4)
    else:
        picture = png.encode(w, h, bytes(image), 3)
        painted = png.encode(w, h, bytes(mask), 1)
    request = InpaintRequest(
        picture,
        painted,
        w,
        h,
        work_w,
        work_h,
        "Continue the plain gray background.",
        "",
        spec,
        sampling,
        mode=mode,
        prefill=False,
        color_match=0.0,
    )
    backend.inpaint(request, progress, None, cancel)
    return _preloaded(app, client, labels[choice])


def _preloaded(app, client: ComfyClient, label: str) -> str:
    app.server.touch()
    return f"{tr('warmed', model=label)} {_summary(_vram(client))}".strip()
