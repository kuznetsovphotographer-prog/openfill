# SPDX-License-Identifier: Apache-2.0
# Modified in the PhotoCraft Workflow Tools fork.
"""English labels for the PhotoCraft companion's added features."""

STRINGS = {
    "brush": "Smart Removal Brush",
    "lasso": "Remove immediately after lasso",
    "remove_now": "Auto Lasso Removal",
    "brush_local": "Smart Removal Brush requires local ComfyUI.",
    "fast": "Light · LaMa",
    "medium": "Medium · RORem",
    "hard": "Heavy · FLUX.1 Fill",
    "size": "Size, px",
    "fit": "Fit",
    "refresh": "Refresh",
    "apply": "Apply",
    "apply_hint": "Apply closes this window. Each result is already on a new layer.",
    "hint": "Paint and release to remove. Right-click or [ ] for brush size; scroll to zoom; middle-drag to pan.",
    "brush_size": "Brush Size",
    "custom_size": "Custom size…",
    "loading": "Loading photo from PhotoCraft…",
    "open_photo": "Open a photo in PhotoCraft first.",
    "size_limit": "The preview supports up to 64 megapixels.",
    "missing": "Model not ready. Connect it, then click Refresh.",
    "busy": "Wait for the current OpenFill operation to finish.",
    "removing": "Removing the masked object…",
    "done": "Done.",
    "stale": "The document changed. Refresh the preview or select the object again.",
    "stale_lasso": "The selection changed. Draw a new lasso.",
    "vram": "Video Memory (VRAM)",
    "preload": "Preload Model",
    "unload": "Unload Models",
    "free": "Free VRAM",
    "header_preload_tip": "Preload selected model for the current tab",
    "header_free_tip": "Free VRAM · unloads all models cached by local ComfyUI",
    "vram_hint": "Unloading frees ComfyUI memory without closing PhotoCraft.",
    "vram_work": "Managing video memory…",
    "vram_local": "Video memory controls require local ComfyUI.",
    "queue_busy": "ComfyUI is busy. Wait for the queue to finish.",
    "vram_stats": "GPU memory free: {free:.1f} of {total:.1f} GiB.",
    "not_running": "Local ComfyUI is not running; there is nothing to unload.",
    "released": "Freed about {delta:.1f} GiB.",
    "released_same": "ComfyUI accepted the unload request; no noticeable change in free memory.",
    "pick_model": "Select an installed local model first.",
    "no_models": "No local models are ready.",
    "warmed": "Preloaded: {model}.",
}


def tr(key: str, **values) -> str:
    return STRINGS[key].format(**values)
