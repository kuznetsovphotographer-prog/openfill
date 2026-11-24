# SPDX-License-Identifier: Apache-2.0
"""Check fork features without PhotoCraft, downloaded models or a running GPU."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "photocraft"), str(ROOT / "gimp-openfill")]

from openfill_photocraft import vram  # noqa: E402
from openfill_photocraft.selection_regions import split_selection  # noqa: E402
from openfill_photocraft.smart_brush import paint_mask  # noqa: E402

from openfill import custom_workflow, geometry, named_fill, workflow  # noqa: E402
from openfill.app import App  # noqa: E402
from openfill.backend import ModelSpec  # noqa: E402


class WorkflowToolsTests(unittest.TestCase):
    def test_rorem_ignores_megapixel_override_but_flux_honors_it(self) -> None:
        """Do not alter RORem's standard profile even when a caller sends an MP value."""
        settings = SimpleNamespace(max_side_sdxl=1024)
        app = SimpleNamespace(settings=settings, uses_cloud=False)
        rorem = ModelSpec(arch="sdxl", template="sdxl_eraser")
        standard = App.profile_for(app, rorem)
        for mp in (1, 2, 3, 4):
            self.assertEqual(App.profile_for(app, rorem, mp), standard)
        flux = ModelSpec(arch="flux", template="flux_fill")
        self.assertEqual(App.profile_for(app, flux, 4).megapixels, 4)

    def test_rorem_hides_resolution_and_leaves_other_model_preference_untouched(self) -> None:
        """Switching away from RORem restores the previously chosen MP value."""
        try:
            from openfill_photocraft.bar import Bar
        except ImportError:
            self.skipTest("no tkinter")
        panel = SimpleNamespace(
            _model=lambda: "rorem-sdxl",
            tab=SimpleNamespace(get=lambda: "remove"),
            service=SimpleNamespace(app=SimpleNamespace(uses_cloud=False)),
            resolution_mp=3,
        )
        self.assertIsNone(Bar.generation_resolution(panel))
        self.assertIsNone(Bar.generation_resolution(panel, "rorem-sdxl"))  # smart brush passes the ID
        for choice in ("flux1-fill-dev-fp8", "custom-workflow:flux2-klein", "custom-workflow:qwen-edit"):
            self.assertEqual(Bar.generation_resolution(panel, choice), 3)

    def test_resolution_in_flux_and_custom_workflows(self) -> None:
        """All three graphs receive the new work size and keep the output bounds."""
        presets = named_fill.load(ROOT / "photocraft" / "examples")
        self.assertEqual(set(presets), {"custom-workflow:flux2-klein", "custom-workflow:qwen-edit"})
        native = ModelSpec(arch="flux", unet="fill.safetensors", clip1="t5.safetensors", vae="vae.safetensors")
        observed = []
        for mp, qwen_side in enumerate((1024, 1408, 1728, 2016), 1):
            work = geometry.working_size(1300, 1000, geometry.with_megapixels(geometry.FLUX, mp))
            self.assertLessEqual(work.width * work.height, mp * 1_000_000)
            observed.append((work.width, work.height))
            req = workflow.PlannedInpaintRequest(
                b"", b"", 1300, 1000, work.width, work.height, "test", "", native, megapixels=mp
            )
            graph = workflow.build_flux_fill(req, "input", "mask", 123, workflow.Capabilities())
            sizes = [(n["inputs"].get("width"), n["inputs"].get("height")) for n in graph.values()]
            self.assertIn((work.width, work.height), sizes)
            for key, preset in presets.items():
                custom = custom_workflow.load(preset.path, preset.inputs)
                req.model = ModelSpec(arch="custom", custom=custom)
                graph = workflow.build_custom(req, "input", "mask", 123, workflow.Capabilities())
                output = custom_workflow.output_node(graph)
                self.assertEqual(graph[output]["class_type"], "SaveImage")
                out = graph[output]["inputs"]["images"][0]
                self.assertEqual((graph[out]["inputs"]["width"], graph[out]["inputs"]["height"]), (1300, 1000))
                if key.endswith(":qwen-edit"):
                    self.assertEqual(graph["condition"]["inputs"]["resolution"], qwen_side)
                else:
                    scaled = graph["size"]["inputs"]["image"][0]
                    self.assertEqual(graph["encode"]["inputs"]["pixels"], [scaled, 0])
                    self.assertEqual(
                        (graph[scaled]["inputs"]["width"], graph[scaled]["inputs"]["height"]), observed[-1]
                    )
        self.assertEqual(len(set(observed)), 4)

    def test_separate_masks_preserve_gray_edges(self) -> None:
        """Diagonal neighbours share a region; separated regions retain alpha."""
        mask = Image.new("L", (12, 12))
        mask.putpixel((2, 1), 60)
        mask.putpixel((3, 2), 199)
        mask.putpixel((7, 9), 35)
        areas = split_selection(mask)
        self.assertEqual([a.rect for a in areas], [geometry.Rect(2, 1, 2, 2), geometry.Rect(7, 9, 1, 1)])
        self.assertEqual(areas[0].grayscale.getpixel((0, 0)), 60)
        self.assertEqual(areas[0].grayscale.getpixel((1, 0)), 0)
        self.assertEqual(areas[1].grayscale.getpixel((0, 0)), 35)

    def test_brush_mask_is_clipped_to_the_document(self) -> None:
        """A stroke against a canvas edge cannot produce out-of-bounds pixels."""
        brush = paint_mask([(0, 4), (3, 4)], (20, 20), 6)
        self.assertEqual(brush.rect.x, 0)
        self.assertLess(brush.rect.width, 20)
        self.assertEqual(brush.grayscale.getpixel((1, 4 - brush.rect.y)), 255)

    @mock.patch.object(vram, "ComfyClient")
    def test_vram_release_refuses_busy_queue_and_remote_engines(self, cls) -> None:
        """Free VRAM only touches an idle, local ComfyUI instance."""
        settings = SimpleNamespace(backend="comfyui", uses_remote=False)
        app = SimpleNamespace(settings=settings, server=mock.Mock())
        app.server.url.return_value = "http://127.0.0.1:8188"
        app.server.is_healthy.return_value = True
        engine = cls.return_value
        engine.queue.return_value = {"queue_running": [object()]}
        with self.assertRaises(RuntimeError):
            vram.unload(app)
        engine.release_memory.assert_not_called()
        engine.queue.return_value = {"queue_running": [], "queue_pending": []}
        engine.system_stats.side_effect = [
            {"devices": [{"type": "cuda", "vram_total": 2**33, "vram_free": 2**30}]},
            {"devices": [{"type": "cuda", "vram_total": 2**33, "vram_free": 2**32}]},
        ]
        with mock.patch.object(vram.time, "sleep"):
            vram.unload(app)
        engine.release_memory.assert_called_once()
        settings.uses_remote = True
        with self.assertRaises(RuntimeError):
            vram.unload(app)
        engine.release_memory.assert_called_once()
