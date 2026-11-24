# SPDX-License-Identifier: Apache-2.0
# Modified in the PhotoCraft Workflow Tools fork.
"""Paint an OpenFill mask on a zoomable preview of the active PhotoCraft document."""

from __future__ import annotations

import math
import sys
import threading
import tkinter as tk
from tkinter import simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk

from openfill.geometry import Rect

from .bridge import BrushSelection
from .localization import tr

MODES = ("fast", "medium", "hard")
BRUSH_PRESETS = (5, 10, 20, 35, 50, 75, 100, 150, 250, 400, 600, 900)


def paint_mask(points, dimensions, diameter: int) -> BrushSelection:
    """Rasterize the stroke in document pixels; never alters the live selection."""
    w, h = dimensions
    radius = diameter / 2
    x0 = max(0, math.floor(min(p[0] for p in points) - radius - 1))
    y0 = max(0, math.floor(min(p[1] for p in points) - radius - 1))
    x1 = min(w, math.ceil(max(p[0] for p in points) + radius + 1))
    y1 = min(h, math.ceil(max(p[1] for p in points) + radius + 1))
    mask = Image.new("L", (x1 - x0, y1 - y0))
    xy = [(x - x0, y - y0) for x, y in points]
    draw = ImageDraw.Draw(mask)
    if len(xy) > 1:
        draw.line(xy, fill=255, width=diameter, joint="curve")
    for x, y in xy:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return BrushSelection(Rect(x0, y0, mask.width, mask.height), mask)


class BrushWindow:
    def __init__(self, bar):
        self.bar, self.service = bar, bar.service
        self.win = tk.Toplevel(bar.root)
        self.win.title(f"{tr('brush')} — OpenFill")
        self.win.geometry("1160x830")
        self.win.minsize(740, 450)
        self.status = tk.StringVar(self.win, tr("loading"))
        self.diameter = tk.StringVar(self.win, "50")
        self.zoom_value = tk.StringVar(self.win)
        self.source = self.photo = None
        self.expected = None
        self.models = {}
        self.scale, self.x, self.y = 1.0, 0.0, 0.0
        self.points, self.pan_at = [], None
        self.stroke = None
        self.pending = self.loading = False
        self.fitted = True

        tools = ttk.Frame(self.win, padding=(8, 6))
        tools.pack(fill="x")
        self.tools = tools
        self.picker = ttk.Combobox(tools, width=23, state="readonly", values=[tr(key) for key in MODES])
        self.picker.current(0)
        self.picker.pack(side="left")
        ttk.Label(tools, text=tr("size")).pack(side="left", padx=(10, 4))
        self.size_field = ttk.Spinbox(tools, from_=2, to=900, increment=5, width=6, textvariable=self.diameter)
        self.size_field.pack(side="left")
        self.size_field.bind("<KeyPress>", self._brush_key)
        for key, fun in (("fit", self.fit), ("100%", self.actual), ("refresh", self.load)):
            button = ttk.Button(tools, text=key if key == "100%" else tr(key), command=fun, width=10)
            button.pack(side="left", padx=(5, 0))
        ttk.Label(tools, textvariable=self.zoom_value).pack(side="left", padx=8)
        self.apply_button = tk.Button(
            tools,
            text=tr("apply"),
            command=self.apply,
            bg="#245db7",
            fg="#ffffff",
            activebackground="#1c4c98",
            activeforeground="#ffffff",
            disabledforeground="#526378",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightcolor="#245db7",
            highlightbackground="#d7deea",
            padx=13,
            pady=3,
        )
        self.apply_button.pack(side="left", padx=(5, 0))
        actions = ttk.Frame(self.win, padding=(8, 0, 8, 7))
        actions.pack(fill="x")
        self.actions = actions
        ttk.Label(actions, text=tr("apply_hint")).pack(side="left")
        for key, action in (("free", self.unload), ("preload", self.preload)):
            ttk.Button(actions, text=tr(key), command=action).pack(side="right", padx=(0, 5))
        ttk.Label(self.win, textvariable=self.status, padding=8).pack(side="bottom", anchor="w")
        self.canvas = tk.Canvas(self.win, bg="#242424", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.fit() if self.fitted else self.draw())
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", self.wheel)
        self.canvas.bind("<Button-5>", self.wheel)
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.end)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Leave>", lambda _: self.canvas.delete("cursor"))
        self.canvas.bind("<ButtonPress-2>", self.pan_start)
        self.canvas.bind("<B2-Motion>", self.pan_move)
        self.canvas.bind("<ButtonRelease-2>", self.pan_end)
        self.canvas.bind("<ButtonRelease-3>", self._brush_menu)
        self.win.bind("<KeyPress>", self._brush_key)
        self.win.bind("<Escape>", lambda _: self.win.destroy())
        self.win.bind("<Return>", self._enter)
        self._sync_buttons()
        try:
            self.win.state("zoomed")
        except tk.TclError:
            pass
        self.win.after_idle(self._fit_toolbar)
        self.win.after_idle(self.load)

    def size(self):
        try:
            return max(2, min(900, int(self.diameter.get())))
        except ValueError:
            return 50

    def _brush_key(self, event):
        if event.state & (0x4 | 0x8 | 0x20000):  # Ctrl / Alt, including Windows Alt
            return None
        # Also honor the physical bracket keys on the Russian keyboard layout.
        direction = {"bracketleft": -1, "bracketright": 1, "Cyrillic_ha": -1, "Cyrillic_hardsign": 1}.get(
            event.keysym, 0
        )
        if not direction and sys.platform == "win32":
            direction = {219: -1, 221: 1}.get(event.keycode, 0)
        if direction:
            size = self.size()
            step = 1 if size <= 10 else 5 if size <= 50 else 10 if size <= 100 else 25 if size <= 250 else 50
            self._set_size(size + direction * step)
            return "break"
        return None

    def _set_size(self, size):
        self.diameter.set(str(max(2, min(900, int(size)))))
        mx, my = self.canvas.winfo_pointerxy()
        if self.canvas.winfo_containing(mx, my) == self.canvas:
            self._show_cursor(mx - self.canvas.winfo_rootx(), my - self.canvas.winfo_rooty())

    def _custom_size(self):
        value = simpledialog.askinteger(
            tr("brush_size"), tr("size"), parent=self.win, initialvalue=self.size(), minvalue=2, maxvalue=900
        )
        if value is not None:
            self._set_size(value)

    def _brush_menu(self, event):
        if self.points or self.pan_at:
            return "break"
        self.canvas.focus_set()
        self.canvas.delete("cursor")
        menu = tk.Menu(self.win, tearoff=False)
        menu.add_command(label=f"{tr('brush_size')} · {self.size()} px", state="disabled")
        menu.add_separator()
        for size in BRUSH_PRESETS:
            menu.add_radiobutton(
                label=f"{size} px", variable=self.diameter, value=str(size), command=lambda n=size: self._set_size(n)
            )
        menu.add_separator()
        menu.add_command(label=tr("custom_size"), command=self._custom_size)
        # Replace the last popup after it has closed; do not accumulate Tk menus.
        previous = getattr(self, "_size_menu", None)
        if previous is not None:
            previous.destroy()
        self._size_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def key(self):
        index = self.picker.current()
        return MODES[index] if index >= 0 else MODES[0]

    def say(self, key):
        self.status.set(tr(key))

    def say_detail(self, text):
        self.status.set(text)

    def _fit_toolbar(self):
        self.win.minsize(max(740, self.tools.winfo_reqwidth(), self.actions.winfo_reqwidth()), 450)

    def _sync_buttons(self):
        ready = not self.pending and not self.points
        self.apply_button.configure(state="normal" if ready else "disabled", bg="#245db7" if ready else "#d7deea")

    def _enter(self, e):
        if e.widget.winfo_class() not in {"TSpinbox", "TCombobox", "TCheckbutton", "TButton"}:
            self.apply()
            return "break"

    def apply(self):
        """Finish the preview; successful strokes are already in separate layers."""
        if not self.pending and not self.points:
            self.win.destroy()

    def load(self):
        if self.loading or self.pending or self.service.busy():
            return
        self.loading = True
        self.expected = None
        self._sync_buttons()
        self.say("loading")

        def work():
            try:
                svc = self.service
                state = svc.client.call("ui.inspect")
                session = state.get("session") or {}
                d = state.get("document") or {}
                name = next((r for r in session.get("documents") or [] if r.get("index") == session.get("active")), {})
                if not d or not name or str(name.get("name", "")).startswith("OpenFill "):
                    self.bar.call_soon(self.loaded, None, None, {}, "", "open_photo")
                    return
                if int(d.get("width", 0)) * int(d.get("height", 0)) > 64_000_000:
                    self.bar.call_soon(self.loaded, None, None, {}, "", "size_limit")
                    return
                expected = (name["index"], name["name"], name["revision"])
                image = svc.bridge.active_image()
                svc._verify_target(expected)
                visible, _ = svc.bridge._snapshot(image)
                svc._verify_target(expected)
                self.bar.call_soon(self.loaded, visible, expected, svc.brush_models(), "")
            except Exception as exc:
                self.bar.call_soon(self.loaded, None, None, {}, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def loaded(self, image, expected, models, error, error_key=None):
        if not self.win.winfo_exists():
            return
        self.loading = False
        if error or error_key:
            self._sync_buttons()
            self.say(error_key) if error_key else self.say_detail(error)
            return
        same = self.source is not None and self.source.size == image.size and self.expected_doc == expected[:2]
        self.source, self.expected, self.expected_doc, self.models = image, expected, expected[:2], models
        if same and not self.fitted:
            self.draw()
        else:
            self.fit()
        self._sync_buttons()
        self.say("hint")

    def fit(self):
        if self.source is None or self.points:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 8 or h < 8:
            return
        a, b = self.source.size
        self.scale = min(w / a, h / b)
        self.x, self.y = (w - a * self.scale) / 2, (h - b * self.scale) / 2
        self.fitted = True
        self.draw()

    def actual(self):
        self.zoom(1, self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    def wheel(self, e):
        factor = 1.22 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1 / 1.22
        self.zoom(self.scale * factor, e.x, e.y)
        return "break"

    def zoom(self, scale, x, y):
        if self.source is None or self.points:
            return
        scale = min(8.0, max(0.015, scale))
        self.x, self.y = x - (x - self.x) * scale / self.scale, y - (y - self.y) * scale / self.scale
        self.scale, self.fitted = scale, False
        self.draw()

    def draw(self):
        if self.source is None:
            return
        c = self.canvas
        c.delete("image", "cursor")
        s, x, y = self.scale, self.x, self.y
        w, h = self.source.size
        left, top = max(0, int(-x / s)), max(0, int(-y / s))
        right = min(w, math.ceil((c.winfo_width() - x) / s))
        bottom = min(h, math.ceil((c.winfo_height() - y) / s))
        if left < right and top < bottom:
            crop = self.source.crop((left, top, right, bottom))
            crop = crop.resize(
                (max(1, round(crop.width * s)), max(1, round(crop.height * s))),
                Image.Resampling.LANCZOS if s < 1 else Image.Resampling.BILINEAR,
            )
            self.photo = ImageTk.PhotoImage(crop, master=c)
            c.create_image(x + left * s, y + top * s, image=self.photo, anchor="nw", tags="image")
            c.tag_lower("image")
        self.zoom_value.set(f"{s * 100:.0f}%")
        self._redraw_marks()

    def _redraw_marks(self):
        if self.points:
            return
        self.canvas.delete("stroke")
        if self.stroke:
            points, diameter = self.stroke
            coords = [v for x, y in points for v in (x * self.scale + self.x, y * self.scale + self.y)]
            width = max(1, diameter * self.scale)
            if len(points) > 1 and any(p != points[0] for p in points[1:]):
                self.canvas.create_line(
                    *coords,
                    width=width,
                    fill="#e64796",
                    stipple="gray50",
                    capstyle="round",
                    joinstyle="round",
                    tags="stroke",
                )
            else:
                x, y = coords[:2]
                r = width / 2
                self.canvas.create_oval(
                    x - r, y - r, x + r, y + r, fill="#e64796", width=0, stipple="gray50", tags="stroke"
                )

    def hover(self, e):
        self._show_cursor(e.x, e.y)

    def _show_cursor(self, x, y):
        self.canvas.delete("cursor")
        if self.source is None or self.points or self.pan_at or self.pending:
            return
        r = max(3, self.size() * self.scale / 2)
        self.canvas.create_oval(x - r, y - r, x + r, y + r, outline="#ff71b9", tags="cursor")

    def pan_start(self, e):
        if not self.points:
            self.pan_at = (e.x, e.y)

    def pan_move(self, e):
        if self.pan_at:
            self.x += e.x - self.pan_at[0]
            self.y += e.y - self.pan_at[1]
            self.pan_at, self.fitted = (e.x, e.y), False
            self.draw()

    def pan_end(self, _):
        self.pan_at = None

    def doc_point(self, e):
        return (e.x - self.x) / self.scale, (e.y - self.y) / self.scale

    def begin(self, e):
        if self.source is None or not self.expected or self.loading or self.pending or self.service.busy():
            return
        if self.key() not in self.models:
            self.say("missing")
            return
        x, y = self.doc_point(e)
        if not (0 <= x < self.source.width and 0 <= y < self.source.height):
            return
        self.canvas.focus_set()
        self.canvas.delete("cursor")
        self.stroke_size = self.size()
        self.points = [(x, y)]
        self._sync_buttons()
        self.last = e.x, e.y
        r = max(1, self.stroke_size * self.scale / 2)
        self.canvas.create_oval(
            e.x - r, e.y - r, e.x + r, e.y + r, fill="#e64796", width=0, stipple="gray50", tags="stroke"
        )

    def move(self, e):
        if not self.points or len(self.points) > 8000:
            return
        x, y = self.doc_point(e)
        x = min(self.source.width - 1, max(0, x))
        y = min(self.source.height - 1, max(0, y))
        self.points.append((x, y))
        here = (x * self.scale + self.x, y * self.scale + self.y)
        self.canvas.create_line(
            *self.last,
            *here,
            width=max(1, self.stroke_size * self.scale),
            fill="#e64796",
            stipple="gray50",
            capstyle="round",
            tags="stroke",
        )
        self.last = here

    def end(self, e):
        if not self.points:
            return
        self.move(e)
        self.stroke = (self.points, self.stroke_size)
        self.points = []
        try:
            if self.service.busy():
                raise RuntimeError(tr("busy"))
            points, diameter = self.stroke
            mask = paint_mask(points, self.source.size, diameter)
            model = self.models[self.key()]
            self.service.start(
                "fill",
                {
                    "remove": True,
                    "removal": model,
                    "megapixels": self.bar.generation_resolution(model),
                    "expected_target": self.expected,
                    "brush_mask": mask,
                },
            )
            self.wait("removing")
        except Exception as exc:
            self.stroke = None
            self.canvas.delete("stroke")
            self._sync_buttons()
            self.say_detail(str(exc))

    def wait(self, key, refresh=True):
        self.pending = True
        self._sync_buttons()
        self.say(key)
        self.win.after(200, lambda: self.poll(refresh))

    def poll(self, refresh):
        if self.service.busy():
            self.win.after(220, lambda: self.poll(refresh))
            return
        self.pending = False
        self.stroke = None
        self.canvas.delete("stroke")
        state = self.service.state.snapshot()
        if refresh and state.get("state") == "done":
            self.load()
        else:
            self._sync_buttons()
            detail = state.get("message") or state.get("text")
            self.say_detail(detail) if detail else self.say("done")

    def memory(self, kind, model=""):
        if self.loading or self.pending or self.service.busy():
            return
        try:
            self.service.start(kind, {"model": model})
            self.wait("vram_work", refresh=False)
        except Exception as exc:
            self.say_detail(str(exc))

    def preload(self):
        model = self.models.get(self.key())
        if model:
            self.memory("preload", model)
        else:
            self.say("missing")

    def unload(self):
        self.memory("vram-free")
