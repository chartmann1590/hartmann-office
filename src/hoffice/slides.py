# SPDX-License-Identifier: GPL-3.0-or-later
"""Presentations: a live slide preview over the slide's fields, and Present.

The slide is drawn by render.draw_slide, the same code the PDF export uses,
so what you see is what you present and what you export. Fields are LumaUI
(TextField, ParagraphField); moving between slides lives in the bar.
"""
from __future__ import annotations

import copy

from gi.repository import Adw, Gdk, GObject, Graphene, Gtk

from luma_appkit import Inset, ParagraphField, ScrollView, TextField, TypeLabel
from luma_appkit.action_bubble import MenuItem

from . import render

__all__ = ["SlideEditor", "Presenter", "LAYOUT_NAMES"]

LAYOUT_NAMES = {"title": ("Title slide", "type"), "content": ("Title and points", "list"),
                "section": ("Section break", "rows-2"), "blank": ("Blank", "square")}


def autosize(field: ParagraphField, min_lines: int):
    """Give a ParagraphField the height of its lines (at least `min_lines`), growing as it is typed into.

    Inside the window's yielding layout a text view is measured before GTK has laid its lines out,
    which reads as 0 tall; an explicit height keeps the paragraph on screen."""
    def fit(*_):
        metrics = field.get_pango_context().get_metrics(None, None)
        line = (metrics.get_ascent() + metrics.get_descent()) / 1024 * 1.35
        width = max(200, field.get_width() or 600)
        chars = max(20, int(width / max(6.0, metrics.get_approximate_char_width() / 1024)))
        lines = sum(max(1, -(-len(x) // chars)) for x in field.text.split("\n"))
        field.set_size_request(-1, int(max(min_lines, lines) * line) + 4)
    field.get_buffer().connect("changed", fit)
    field.connect("map", fit)
    fit()


class SlideCanvas(Gtk.Widget):
    """The current slide at 16:9, as tall as its width asks (height-for-width)."""

    __gtype_name__ = "HofficeSlideCanvas"

    def __init__(self, editor: "SlideEditor"):
        super().__init__(hexpand=True, accessible_role=Gtk.AccessibleRole.IMG)
        self.editor = editor

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 160, 860, -1, -1
        w = for_size if for_size > 0 else 860
        h = int(w * 9 / 16)
        return h, h, -1, -1

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        if width < 2 or height < 2:
            return
        cr = snapshot.append_cairo(Graphene.Rect().init(0, 0, width, height))
        self._draw(None, cr, width, height)

    def _draw(self, _area, cr, width, height):
        s = self.editor.slide
        w = min(width, height * 16 / 9)
        h = w * 9 / 16
        cr.translate((width - w) / 2, (height - h) / 2)
        cr.save()
        radius = 12
        cr.new_sub_path()
        for (x, y, a) in ((w - radius, radius, -1.5708), (w - radius, h - radius, 0), (radius, h - radius, 1.5708),
                          (radius, radius, 3.1416)):
            cr.arc(x, y, radius, a, a + 1.5708)
        cr.close_path()
        cr.clip()
        render.draw_slide(cr, w, h, s, self.editor.model.get("theme", "paper"), self.editor.index + 1)
        cr.restore()


class SlideEditor(Gtk.Box):
    """One open presentation. Emits `changed` after edits and `moved` when the current slide changes."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "moved": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, model: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.add_css_class("hoffice-slides")
        self.model = model
        self.index = 0
        self._loading = False
        self.undo_stack: list = []
        self.redo_stack: list = []

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=20, margin_bottom=130,
                         margin_start=16, margin_end=16)
        self.canvas = SlideCanvas(self)
        column.append(self.canvas)
        self.position = TypeLabel("", role="caption")
        self.position.set_halign(Gtk.Align.CENTER)
        column.append(self.position)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.title_field = TextField("Title", placeholder="Slide title", on_changed=lambda t: self._edit("title", t))
        self.body_field = ParagraphField(placeholder="One point per line. Start a line with two spaces to indent it.",
                                         label="Text")
        self.body_field.get_buffer().connect("changed", lambda b: self._edit("body", self.body_field.text))
        self.notes_field = ParagraphField(placeholder="Speaker notes. Only you see these.", label="Speaker notes")
        self.notes_field.get_buffer().connect("changed", lambda b: self._edit("notes", self.notes_field.text))
        self.body_label = TypeLabel("Text", role="label")
        self.notes_label = TypeLabel("Speaker notes", role="label")
        autosize(self.body_field, 3)
        autosize(self.notes_field, 2)
        self.body_well = Inset(padding="card")
        self.body_well.append(self.body_field)
        self.notes_well = Inset(padding="card")
        self.notes_well.append(self.notes_field)
        box.append(self.title_field)
        for label, well in ((self.body_label, self.body_well), (self.notes_label, self.notes_well)):
            label.set_margin_top(6)
            box.append(label)
            box.append(well)
        column.append(box)
        clamp = Adw.Clamp(maximum_size=880, tightening_threshold=600, child=column)
        self.scroll = ScrollView(clamp, vexpand=True)
        self.append(self.scroll)
        self.show_slide(0)

    @property
    def slide(self) -> dict:
        return self.model["slides"][self.index]

    @staticmethod
    def _set_field(field, text):
        if isinstance(field, ParagraphField):
            field.get_buffer().set_text(text)
        else:
            field.text = text

    def show_slide(self, i: int):
        self.index = max(0, min(i, len(self.model["slides"]) - 1))
        self._loading = True
        s = self.slide
        self._set_field(self.title_field, s.get("title", ""))
        self._set_field(self.body_field, s.get("body", ""))
        self._set_field(self.notes_field, s.get("notes", ""))
        for w in (self.body_well, self.body_label):
            w.set_visible(s.get("layout") in ("content", "title"))
        self.body_label.set_text("Subtitle" if s.get("layout") == "title" else "Points")
        self.title_field.set_visible(s.get("layout") != "blank")
        self._loading = False
        self.position.set_text(f"Slide {self.index + 1} of {len(self.model['slides'])} · "
                                f"{LAYOUT_NAMES[s.get('layout', 'content')][0]}")
        self.canvas.update_property([Gtk.AccessibleProperty.LABEL],
                                    [f"Slide {self.index + 1}: {s.get('title') or 'untitled'}"])
        self.canvas.queue_draw()
        self.emit("moved")

    def _record(self):
        self.undo_stack.append((copy.deepcopy(self.model), self.index))
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def _edit(self, key, text):
        if self._loading:
            return
        if self.slide.get(key) == text:
            return
        if not self.undo_stack or self.undo_stack[-1][2:] != (key, self.index):
            self.undo_stack.append((copy.deepcopy(self.model), self.index, key, self.index))
            self.redo_stack.clear()
        self.slide[key] = text
        self.canvas.queue_draw()
        self.emit("changed")

    def _structural(self):
        self.undo_stack.append((copy.deepcopy(self.model), self.index))
        self.redo_stack.clear()

    def add_slide(self, layout="content"):
        self._structural()
        self.model["slides"].insert(self.index + 1, {"layout": layout, "title": "", "body": "", "notes": ""})
        self.show_slide(self.index + 1)
        self.emit("changed")
        self.title_field.grab_focus()

    def duplicate_slide(self):
        self._structural()
        self.model["slides"].insert(self.index + 1, copy.deepcopy(self.slide))
        self.show_slide(self.index + 1)
        self.emit("changed")

    def delete_slide(self) -> bool:
        if len(self.model["slides"]) < 2:
            return False
        self._structural()
        self.model["slides"].pop(self.index)
        self.show_slide(min(self.index, len(self.model["slides"]) - 1))
        self.emit("changed")
        return True

    def move_slide(self, delta: int):
        j = self.index + delta
        if 0 <= j < len(self.model["slides"]):
            self._structural()
            s = self.model["slides"]
            s[self.index], s[j] = s[j], s[self.index]
            self.show_slide(j)
            self.emit("changed")

    def set_layout(self, layout: str):
        self._structural()
        self.slide["layout"] = layout
        self.show_slide(self.index)
        self.emit("changed")

    def set_theme(self, theme: str):
        self._structural()
        self.model["theme"] = theme
        self.canvas.queue_draw()
        self.emit("changed")

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        state = self.undo_stack.pop()
        self.redo_stack.append((copy.deepcopy(self.model), self.index))
        self.model.clear()
        self.model.update(state[0])
        self.show_slide(state[1])
        self.emit("changed")
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        state = self.redo_stack.pop()
        self.undo_stack.append((copy.deepcopy(self.model), self.index))
        self.model.clear()
        self.model.update(state[0])
        self.show_slide(state[1])
        self.emit("changed")
        return True

    def layout_rows(self):
        cur = self.slide.get("layout")
        return [MenuItem(name, icon=icon, selected=(k == cur), on_activate=lambda k=k: self.set_layout(k))
                for k, (name, icon) in LAYOUT_NAMES.items()]

    def theme_rows(self):
        cur = self.model.get("theme", "paper")
        return [MenuItem(t[3], icon="palette", selected=(k == cur), on_activate=lambda k=k: self.set_theme(k))
                for k, t in render.THEMES.items()]


class Presenter(Gtk.Window):
    """Full screen slides. Space, → or a click goes on; ← goes back; Esc ends."""

    def __init__(self, parent: Gtk.Window, model: dict, start: int = 0):
        super().__init__(transient_for=parent, modal=True, title="Presenting", decorated=False)
        self.model, self.index = model, start
        self.add_css_class("hoffice-presenter")
        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True, focusable=True, accessible_role=Gtk.AccessibleRole.IMG)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        click = Gtk.GestureClick(button=0)
        click.connect("released", self._click)
        self.area.add_controller(click)
        self._label()
        self.fullscreen()

    def _label(self):
        s = self.model["slides"][self.index]
        self.area.update_property([Gtk.AccessibleProperty.LABEL],
                                  [f"Slide {self.index + 1} of {len(self.model['slides'])}: {s.get('title', '')}. "
                                   f"{s.get('body', '')}"])

    def _draw(self, _a, cr, width, height):
        cr.set_source_rgb(0, 0, 0)  # letterbox around a 16:9 slide on any screen
        cr.paint()
        w = min(width, height * 16 / 9)
        h = w * 9 / 16
        cr.translate((width - w) / 2, (height - h) / 2)
        render.draw_slide(cr, w, h, self.model["slides"][self.index], self.model.get("theme", "paper"), self.index + 1)

    def go(self, delta: int):
        j = self.index + delta
        if j >= len(self.model["slides"]):
            self.close()
            return
        self.index = max(0, j)
        self._label()
        self.area.queue_draw()

    def _key(self, _c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.close()
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_space, Gdk.KEY_Page_Down, Gdk.KEY_Down, Gdk.KEY_Return, Gdk.KEY_n):
            self.go(1)
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up, Gdk.KEY_Up, Gdk.KEY_BackSpace, Gdk.KEY_p):
            self.go(-1)
        elif keyval == Gdk.KEY_Home:
            self.go(-self.index)
        elif keyval == Gdk.KEY_End:
            self.go(len(self.model["slides"]) - 1 - self.index)
        else:
            return False
        return True

    def _click(self, gesture, _n, x, _y):
        if gesture.get_current_button() == 3 or x < self.get_width() * 0.25:
            self.go(-1)
        else:
            self.go(1)
