# PhotoCraft Workflow Tools

An unofficial fork of Beckett Harriman's OpenFill for PhotoCraft 0.2.7. This branch adds tools for local retouching; it does not include a Photoshop plugin or model weights.

## Try it

1. Download the fork branch as source or clone it. Run `photocraft/Install OpenFill for PhotoCraft.cmd` on Windows, or use the [upstream installation guide](README.md) for the corresponding platform. Installing the fork replaces the same OpenFill application files as upstream; it is not a second independent installation. Close PhotoCraft and OpenFill before switching between builds and back up existing customizations first.
2. Open **PhotoCraft with OpenFill**. Select your existing ComfyUI installation in **Settings → Engine** and reuse its models. Windows was the development environment; the fork has not been independently validated on Linux or macOS.
3. For models that support it, choose **Model → Resolution (1, 2, 3 or 4 MP)**. This changes the model's working resolution, not the source document or selection. The actual pixel count depends on aspect ratio and model alignment. Try 1 MP first: higher settings require more VRAM and do not guarantee a better result. RORem always uses OpenFill's standard SDXL eraser sizing, including in the smart brush. Native LaMa/MAT, Cutout and Upscale also retain their own sizing.

## Local retouching

- **Load Model** runs a small synthetic job with the selected model. ComfyUI decides which weights to keep resident. **Free VRAM** clears the model cache of the local ComfyUI instance and is blocked while its queue is busy; it does not free VRAM from other applications.
- **Remove → Smart Removal Brush** opens a zoomable preview. Pick LaMa, RORem or FLUX.1 Fill, paint over an object, and release to generate a new layer. Right-click or use `[` and `]` to resize the brush. The pink overlay clears after processing. **Apply** closes the preview; it does not rerun the job. Install any missing model through the normal model manager.
- **Remove immediately after lasso** is opt-in. Turn it off to build several disconnected areas before running a job. Fill, Remove and Create → Layer process separate areas one at a time, with one result layer per area. Completed areas remain after cancellation.

## Optional named ComfyUI workflows

The built-in FLUX.1 Fill entry does not need extra setup. To expose Klein and Qwen alongside it in Fill and Remove, copy the three JSON files from [examples](examples/) into the OpenFill profile. On Windows this is `%APPDATA%\OpenFill for PhotoCraft\openfill`. If you already have a `local-fill-workflows.json`, merge the entries instead of replacing it. The example graphs expect FLUX.2 Klein 9B FP8 and a Qwen Image Edit 2.1 Turbo INT8 workflow; adjust model filenames and bindings to match your separately installed weights and nodes, or substitute a compatible API export. No weights or third-party nodes are installed by copying these examples. Model licenses are separate from this project's code license. The `remove_prompt` field opts a workflow into Remove. Enable `mark_selection` only for models that need a visual mark instead of an input mask.

The test suite checks work dimensions and graph bindings without loading models. Actual speed and attainable resolution depend on the workflow, checkpoints, installed nodes and available GPU memory.
