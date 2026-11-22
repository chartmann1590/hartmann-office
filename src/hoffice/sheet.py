# SPDX-License-Identifier: GPL-3.0-or-later
"""Spreadsheets: a drawn grid that only paints the cells you can see.

The grid is content (like a photo or a game board); its colours come from
LumaUI tokens looked up at draw time, so it follows light, dark and high
contrast. Typing goes into the action bar's field, which is the formula bar.
"""
from __future__ import annotations

import math

import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gtk, Pango, PangoCairo  # noqa: E402

from luma_appkit.action_bubble import MenuItem  # noqa: E402

from . import formula  # noqa: E402

__all__ = ["SheetView", "FORMAT_NAMES"]

FORMAT_NAMES = {"general": "Automatic", "number": "Number (1,234.50)", "currency": "Currency ($1,234.50)",
                "percent": "Percent (12%)", "date": "Date (2026-11-18)", "text": "Text"}
DEFAULT_W = 100
MIN_W = 36
HEADER_W = 48


def _rgba(widget, token, fallback):
    found, c = widget.get_style_context().lookup_color(token)
    if not found:
        c = Gdk.RGBA()
        c.parse(fallback)
    return c


class SheetView(Gtk.Widget):
    """The grid. Emits `selection-changed` and `changed` (cells or sizes edited)."""

    __gtype_name__ = "HofficeSheetView"
    __gsignals__ = {
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "edit-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, model: dict, *, touch: bool = False):
        super().__init__(hexpand=True, vexpand=True, focusable=True, overflow=Gtk.Overflow.HIDDEN,
                         accessible_role=Gtk.AccessibleRole.GRID)
        self.add_css_class("hoffice-sheet")
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Spreadsheet"])
        self.row_h = 40 if touch else 28
        self.head_h = self.row_h
        self.hadj = Gtk.Adjustment()
        self.vadj = Gtk.Adjustment()
        self.hadj.connect("value-changed", lambda *_: self.queue_draw())
        self.vadj.connect("value-changed", lambda *_: self.queue_draw())
        self.cur = (0, 0)
        self.anchor = (0, 0)
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._drag = None
        self._layout_cache: dict = {}
        self.set_model(model)

        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed)
        self.add_controller(click)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", lambda *_: setattr(self, "_drag", None))
        self.add_controller(drag)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES |
                                           Gtk.EventControllerScrollFlags.KINETIC)
        scroll.connect("scroll", self._scrolled)
        self.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    # ------------------------------------------------------------ model
    def set_model(self, model: dict):
        self.model = model
        self.sheet = 0
        self.rebuild()

    def rebuild(self):
        self.wb = formula.Workbook()
        for s in self.model["sheets"]:
            self.wb.add_sheet(s["name"], {tuple(map(int, k.split(","))): v.get("v", "") for k, v in s["cells"].items()})
        self._extent()
        self.queue_draw()

    @property
    def cells(self) -> dict:
        return self.model["sheets"][self.sheet]["cells"]

    @property
    def widths(self) -> dict:
        return self.model["sheets"][self.sheet].setdefault("widths", {})

    def sheet_names(self):
        return [s["name"] for s in self.model["sheets"]]

    def set_sheet(self, i: int):
        self.sheet = max(0, min(i, len(self.model["sheets"]) - 1))
        self.cur = self.anchor = (0, 0)
        self.hadj.set_value(0)
        self.vadj.set_value(0)
        self._extent()
        self.queue_draw()
        self.emit("selection-changed")

    def add_sheet(self) -> int:
        names = set(self.sheet_names())
        n = len(names) + 1
        while f"Sheet {n}" in names:
            n += 1
        self.model["sheets"].append({"name": f"Sheet {n}", "cells": {}, "widths": {}})
        self.wb.add_sheet(f"Sheet {n}")
        self.emit("changed")
        return len(self.model["sheets"]) - 1

    def rename_sheet(self, name: str) -> bool:
        name = name.strip()[:60]
        if not name or name in self.sheet_names() or "!" in name:
            return False
        self.model["sheets"][self.sheet]["name"] = name
        self.rebuild()
        self.emit("changed")
        return True

    def delete_sheet(self) -> dict | None:
        if len(self.model["sheets"]) < 2:
            return None
        gone = self.model["sheets"].pop(self.sheet)
        self.rebuild()
        self.set_sheet(min(self.sheet, len(self.model["sheets"]) - 1))
        self.emit("changed")
        return gone

    # ------------------------------------------------------------ geometry
    def col_w(self, c: int) -> int:
        return int(self.widths.get(str(c), DEFAULT_W))

    def col_x(self, c: int) -> int:
        """x of column c in sheet space (no header)."""
        if not self.widths:
            return c * DEFAULT_W
        return sum(self.col_w(i) for i in range(c))

    def col_at(self, x: float) -> int:
        if not self.widths:
            return max(0, int(x // DEFAULT_W))
        c, acc = 0, 0
        while c < formula.MAX_COLS - 1:
            w = self.col_w(c)
            if acc + w > x:
                return c
            acc += w
            c += 1
        return c

    def _extent(self):
        rows, cols = self.wb.extent(self.sheet)
        self.n_rows = max(rows + 60, 200, self.cur[0] + 40)
        self.n_cols = min(formula.MAX_COLS, max(cols + 8, 26, self.cur[1] + 8))
        self._update_adjustments()

    def _update_adjustments(self):
        w, h = self.get_width(), self.get_height()
        total_w = self.col_x(self.n_cols)
        total_h = self.n_rows * self.row_h + 120  # room to scroll the last rows out from under the bar
        view_w = max(1, w - HEADER_W)
        view_h = max(1, h - self.head_h)
        self.hadj.configure(min(self.hadj.get_value(), max(0, total_w - view_w)), 0, total_w, 40, view_w * 0.9, view_w)
        self.vadj.configure(min(self.vadj.get_value(), max(0, total_h - view_h)), 0, total_h, self.row_h,
                            view_h * 0.9, view_h)

    def do_size_allocate(self, width, height, baseline):
        self._update_adjustments()

    def do_measure(self, orientation, for_size):
        return (200, 600, -1, -1) if orientation == Gtk.Orientation.HORIZONTAL else (160, 400, -1, -1)

    def cell_rect(self, r: int, c: int):
        x = HEADER_W + self.col_x(c) - self.hadj.get_value()
        y = self.head_h + r * self.row_h - self.vadj.get_value()
        return x, y, self.col_w(c), self.row_h

    def hit(self, x: float, y: float):
        """(row, col) under a point; -1 for a header."""
        r = -1 if y < self.head_h else int((y - self.head_h + self.vadj.get_value()) // self.row_h)
        c = -1 if x < HEADER_W else self.col_at(x - HEADER_W + self.hadj.get_value())
        return r, c

    def ensure_visible(self, r: int, c: int):
        x = self.col_x(c)
        w = self.col_w(c)
        vw = self.get_width() - HEADER_W
        hv = self.hadj.get_value()
        if x < hv:
            self.hadj.set_value(x)
        elif x + w > hv + vw:
            self.hadj.set_value(x + w - vw)
        y = r * self.row_h
        vh = self.get_height() - self.head_h
        vv = self.vadj.get_value()
        if y < vv:
            self.vadj.set_value(y)
        elif y + self.row_h > vv + vh:
            self.vadj.set_value(y + self.row_h - vh)

    # ------------------------------------------------------------ selection
    def selection(self):
        (r1, c1), (r2, c2) = self.anchor, self.cur
        return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)

    def select(self, r: int, c: int, extend: bool = False):
        r = max(0, min(r, formula.MAX_ROWS - 1))
        c = max(0, min(c, formula.MAX_COLS - 1))
        self.cur = (r, c)
        if not extend:
            self.anchor = (r, c)
        if r >= self.n_rows - 20 or c >= self.n_cols - 4:
            self._extent()
        self.ensure_visible(r, c)
        self.queue_draw()
        self.emit("selection-changed")
        self.update_property([Gtk.AccessibleProperty.DESCRIPTION],
                             [f"{formula.cell_name(r, c)}: {self.shown(r, c) or 'empty'}"])

    def selection_name(self) -> str:
        r1, c1, r2, c2 = self.selection()
        a = formula.cell_name(r1, c1)
        return a if (r1, c1) == (r2, c2) else f"{a}:{formula.cell_name(r2, c2)}"

    # ------------------------------------------------------------ cells
    def info(self, r, c) -> dict:
        return self.cells.get(f"{r},{c}", {})

    def raw(self, r=None, c=None) -> str:
        r, c = (self.cur if r is None else (r, c))
        return self.info(r, c).get("v", "")

    def value(self, r, c):
        return self.wb.value(self.sheet, r, c)

    def shown(self, r, c) -> str:
        info = self.info(r, c)
        if not info:
            return ""
        return formula.display(self.value(r, c), info.get("fmt", "general"))

    def _snapshot(self, keys):
        return {k: (dict(self.cells[k]) if k in self.cells else None) for k in keys}

    def _commit(self, before: dict, label: str):
        self.undo_stack.append((self.sheet, before, label))
        del self.undo_stack[:-200]
        self.redo_stack.clear()
        self.wb.cells[self.sheet] = {tuple(map(int, k.split(","))): v.get("v", "") for k, v in self.cells.items()}
        self.wb.invalidate()
        self._extent()
        self.queue_draw()
        self.emit("changed")
        self.emit("selection-changed")

    def set_raw(self, r: int, c: int, raw: str, *, record=True):
        key = f"{r},{c}"
        before = self._snapshot([key])
        info = dict(self.cells.get(key, {}))
        if raw.strip() == "" and not any(k for k in info if k != "v"):
            self.cells.pop(key, None)
        else:
            info["v"] = raw
            self.cells[key] = info
        if record:
            self._commit(before, "Edit")

    def apply_to_selection(self, fn, label: str):
        r1, c1, r2, c2 = self.selection()
        keys = [f"{r},{c}" for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        before = self._snapshot(keys)
        for k in keys:
            info = dict(self.cells.get(k, {}))
            fn(info)
            if info.get("v", "") == "" and len(info) <= 1:
                self.cells.pop(k, None)
            else:
                info.setdefault("v", "")
                self.cells[k] = info
        self._commit(before, label)

    def set_bold(self, on: bool):
        self.apply_to_selection(lambda i: i.update(b=on) if on else i.pop("b", None), "Bold")

    def set_italic(self, on: bool):
        self.apply_to_selection(lambda i: i.update(i=on) if on else i.pop("i", None), "Italic")

    def set_align(self, align: str | None):
        self.apply_to_selection(lambda i: i.update(align=align) if align else i.pop("align", None), "Align")

    def set_format(self, fmt: str):
        self.apply_to_selection(lambda i: i.update(fmt=fmt) if fmt != "general" else i.pop("fmt", None), "Format")

    def clear(self):
        self.apply_to_selection(lambda i: i.clear(), "Clear")

    def undo(self) -> bool:
        return self._swap(self.undo_stack, self.redo_stack)

    def redo(self) -> bool:
        return self._swap(self.redo_stack, self.undo_stack)

    def _swap(self, src, dst) -> bool:
        if not src:
            return False
        sheet, state, label = src.pop()
        if sheet >= len(self.model["sheets"]):
            return False
        if sheet != self.sheet:
            self.set_sheet(sheet)
        cells = self.model["sheets"][sheet]["cells"]
        dst.append((sheet, {k: (dict(cells[k]) if k in cells else None) for k in state}, label))
        for k, v in state.items():
            if v is None:
                cells.pop(k, None)
            else:
                cells[k] = v
        self.rebuild()
        self.emit("changed")
        self.emit("selection-changed")
        return True

    # ------------------------------------------------------------ rows and columns
    def _move_cells(self, axis: int, at: int, delta: int, label: str):
        """Insert (delta > 0) or delete (delta < 0) rows/columns at `at`, moving formulas with them."""
        before = {k: dict(v) for k, v in self.cells.items()}
        new = {}
        for k, info in self.cells.items():
            r, c = map(int, k.split(","))
            pos = (r, c)[axis]
            if delta < 0 and at <= pos < at - delta:
                continue
            if pos >= at:
                pos += delta
            rr, cc = (pos, c) if axis == 0 else (r, pos)
            new[f"{rr},{cc}"] = dict(info)
        for info in new.values():
            v = info.get("v", "")
            if v.startswith("="):
                info["v"] = _shift_block(v, axis, at, delta)
        before_keys = set(before) | set(new)
        snapshot = {k: before.get(k) for k in before_keys}
        self.model["sheets"][self.sheet]["cells"] = new
        if axis == 1:
            w = {}
            for k, v in self.widths.items():
                c = int(k)
                if delta < 0 and at <= c < at - delta:
                    continue
                w[str(c + delta if c >= at else c)] = v
            self.model["sheets"][self.sheet]["widths"] = w
        self.undo_stack.append((self.sheet, snapshot, label))
        self.redo_stack.clear()
        self.rebuild()
        self.emit("changed")
        self.emit("selection-changed")

    def insert_rows(self, below=False):
        r1, _, r2, _ = self.selection()
        self._move_cells(0, r2 + 1 if below else r1, r2 - r1 + 1, "Insert rows")

    def delete_rows(self):
        r1, _, r2, _ = self.selection()
        self._move_cells(0, r1, -(r2 - r1 + 1), "Delete rows")
        self.select(r1, self.cur[1])

    def insert_cols(self, right=False):
        _, c1, _, c2 = self.selection()
        self._move_cells(1, c2 + 1 if right else c1, c2 - c1 + 1, "Insert columns")

    def delete_cols(self):
        _, c1, _, c2 = self.selection()
        self._move_cells(1, c1, -(c2 - c1 + 1), "Delete columns")
        self.select(self.cur[0], c1)

    def sort(self, descending=False):
        """Sort the rows of the selection (or the used rows) by the current column."""
        r1, c1, r2, c2 = self.selection()
        rows, cols = self.wb.extent(self.sheet)
        if r1 == r2:
            r1, r2, c1, c2 = (1 if self._looks_like_header() else 0), rows - 1, 0, cols - 1
        key_c = self.cur[1]
        keys = [f"{r},{c}" for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        before = self._snapshot(keys)
        data = [[self.cells.get(f"{r},{c}") for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
        vals = [self.value(r, key_c) for r in range(r1, r2 + 1)]

        def k(i):
            v = vals[i]
            if v is None or v == "":
                return (2, 0, "")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return (0, v, "")
            return (1, 0, str(v).lower())
        order = sorted(range(len(data)), key=k, reverse=descending)
        if descending:  # blanks stay last
            order = [i for i in order if k(i)[0] != 2] + [i for i in order if k(i)[0] == 2]
        for new_r, old_i in enumerate(order):
            for j, info in enumerate(data[old_i]):
                key = f"{r1 + new_r},{c1 + j}"
                if info is None:
                    self.cells.pop(key, None)
                else:
                    info = dict(info)
                    if info.get("v", "").startswith("="):
                        info["v"] = formula.shift_formula(info["v"], new_r - old_i, 0)
                    self.cells[key] = info
        self._commit(before, "Sort")

    def _looks_like_header(self) -> bool:
        rows, cols = self.wb.extent(self.sheet)
        first = [self.value(0, c) for c in range(cols)]
        second = [self.value(1, c) for c in range(cols)] if rows > 1 else []
        return any(isinstance(v, str) for v in first) and any(isinstance(v, float) for v in second)

    def autosum(self) -> str:
        """The formula Sum would put in the current cell: the numbers above, else to the left."""
        r, c = self.cur
        r1, c1, r2, c2 = self.selection()
        if (r1, c1) != (r2, c2):
            return f"=SUM({self.selection_name()})"
        top = r - 1
        while top >= 0 and isinstance(self.value(top, c), float):
            top -= 1
        if top < r - 1:
            return f"=SUM({formula.cell_name(top + 1, c)}:{formula.cell_name(r - 1, c)})"
        left = c - 1
        while left >= 0 and isinstance(self.value(r, left), float):
            left -= 1
        if left < c - 1:
            return f"=SUM({formula.cell_name(r, left + 1)}:{formula.cell_name(r, c - 1)})"
        return "=SUM()"

    def fill_down(self):
        r1, c1, r2, c2 = self.selection()
        if r2 == r1:
            return
        keys = [f"{r},{c}" for r in range(r1 + 1, r2 + 1) for c in range(c1, c2 + 1)]
        before = self._snapshot(keys)
        for c in range(c1, c2 + 1):
            src = self.cells.get(f"{r1},{c}")
            for r in range(r1 + 1, r2 + 1):
                if src is None:
                    self.cells.pop(f"{r},{c}", None)
                else:
                    info = dict(src)
                    info["v"] = formula.shift_formula(src.get("v", ""), r - r1, 0)
                    self.cells[f"{r},{c}"] = info
        self._commit(before, "Fill down")

    # ------------------------------------------------------------ clipboard
    def copy_text(self) -> str:
        r1, c1, r2, c2 = self.selection()
        return "\n".join("\t".join(self.raw(r, c) for c in range(c1, c2 + 1)) for r in range(r1, r2 + 1))

    def paste_text(self, text: str, source_origin: tuple[int, int] | None = None):
        lines = text.rstrip("\n").split("\n")
        r0, c0 = self.selection()[:2]
        keys, cells = [], []
        for i, line in enumerate(lines[:formula.MAX_ROWS]):
            for j, v in enumerate(line.rstrip("\r").split("\t")[:formula.MAX_COLS]):
                keys.append(f"{r0 + i},{c0 + j}")
                if source_origin and v.startswith("="):
                    v = formula.shift_formula(v, r0 - source_origin[0], c0 - source_origin[1])
                cells.append((r0 + i, c0 + j, v))
        before = self._snapshot(keys)
        for r, c, v in cells:
            key = f"{r},{c}"
            info = dict(self.cells.get(key, {}))
            if v == "" and len(info) <= 1:
                self.cells.pop(key, None)
            else:
                info["v"] = v
                self.cells[key] = info
        self.anchor = (r0, c0)
        self.cur = (r0 + len(lines) - 1, c0 + max(len(l.split("\t")) for l in lines) - 1)
        self._commit(before, "Paste")

    # ------------------------------------------------------------ input
    def _pressed(self, gesture, n, x, y):
        self.grab_focus()
        r, c = self.hit(x, y)
        shift = bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        if r < 0 and c < 0:
            self.anchor, self.cur = (0, 0), (self.n_rows - 1, self.n_cols - 1)
            self.queue_draw()
            self.emit("selection-changed")
            return
        if r < 0:  # column header: the whole column, or resize at its right edge
            edge = self._col_edge(x)
            if edge is not None:
                return
            self.anchor = (0, c) if not shift else (0, self.anchor[1])
            self.cur = (self.n_rows - 1, c)
            self.queue_draw()
            self.emit("selection-changed")
            return
        if c < 0:
            self.anchor = (r, 0) if not shift else (self.anchor[0], 0)
            self.cur = (r, self.n_cols - 1)
            self.queue_draw()
            self.emit("selection-changed")
            return
        self.select(r, c, extend=shift)
        if n == 2:
            self.emit("edit-requested", self.raw())

    def _col_edge(self, x):
        for c in range(self.col_at(max(0, x - HEADER_W + self.hadj.get_value() - 8)),
                       self.col_at(x - HEADER_W + self.hadj.get_value() + 8) + 1):
            right = HEADER_W + self.col_x(c + 1) - self.hadj.get_value()
            if abs(x - right) <= 6:
                return c
        return None

    def _drag_begin(self, gesture, x, y):
        r, c = self.hit(x, y)
        if r < 0 <= c or (r < 0 and c < 0):
            edge = self._col_edge(x)
            if edge is not None:
                self._drag = ("resize", edge, self.col_w(edge), x)
                return
        self._drag = ("select", x, y) if r >= 0 and c >= 0 else None

    def _drag_update(self, gesture, dx, dy):
        if not self._drag:
            return
        if self._drag[0] == "resize":
            _, c, w0, _ = self._drag
            self.widths[str(c)] = int(max(MIN_W, min(800, w0 + dx)))
            self._update_adjustments()
            self.queue_draw()
            self.emit("changed")
            return
        _, x0, y0 = self._drag
        r, c = self.hit(x0 + dx, y0 + dy)
        if r >= 0 and c >= 0 and (r, c) != self.cur:
            self.select(r, c, extend=True)

    def _scrolled(self, ctl, dx, dy):
        unit = ctl.get_unit()
        k = 1.0 if unit == Gdk.ScrollUnit.SURFACE else self.row_h * 1.5
        if ctl.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK and not dx:
            dx, dy = dy, 0
        self.hadj.set_value(self.hadj.get_value() + dx * k)
        self.vadj.set_value(self.vadj.get_value() + dy * k)
        return True

    def _key(self, _ctl, keyval, _code, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        r, c = self.cur
        page = max(1, int((self.get_height() - self.head_h) // self.row_h) - 1)
        moves = {Gdk.KEY_Up: (-1, 0), Gdk.KEY_Down: (1, 0), Gdk.KEY_Left: (0, -1), Gdk.KEY_Right: (0, 1),
                 Gdk.KEY_Page_Up: (-page, 0), Gdk.KEY_Page_Down: (page, 0)}
        if keyval in moves:
            dr, dc = moves[keyval]
            if ctrl:  # to the edge of the data
                rows, cols = self.wb.extent(self.sheet)
                r = 0 if dr < 0 else (rows - 1 if dr > 0 else r)
                c = 0 if dc < 0 else (cols - 1 if dc > 0 else c)
                self.select(r, c, extend=shift)
            else:
                self.select(r + dr, c + dc, extend=shift)
            return True
        if keyval in (Gdk.KEY_Home,):
            self.select(0 if ctrl else r, 0, extend=shift)
            return True
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and not ctrl:
            self.select(r, c + (-1 if shift or keyval == Gdk.KEY_ISO_Left_Tab else 1))
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.select(r + (-1 if shift else 1), c)
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.apply_to_selection(lambda i: i.pop("v", None), "Clear")
            return True
        if keyval == Gdk.KEY_F2:
            self.emit("edit-requested", self.raw())
            return True
        if ctrl:
            return False
        ch = Gdk.keyval_to_unicode(keyval)
        if ch and ch >= 32 and not (state & Gdk.ModifierType.ALT_MASK):
            # start typing over the cell. "\x01", not "\0": a GObject str argument is a C string, so "\0" + key
            # arrived as "" and the first key was lost ("12" became "2", "=SUM(...)" lost its "=").
            self.emit("edit-requested", "\x01" + chr(ch))
            return True
        return False

    # ------------------------------------------------------------ drawing
    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        cr = snapshot.append_cairo(Graphene.Rect().init(0, 0, w, h))
        ink = _rgba(self, "luma_ink", "#1c1c1c")
        muted = _rgba(self, "luma_muted", "#6b6b6b")
        line = _rgba(self, "luma_hairline", "rgba(0,0,0,0.08)")
        fill = _rgba(self, "luma_fill", "rgba(0,0,0,0.04)")
        accent = _rgba(self, "luma_accent", "#2f6fde")
        soft = _rgba(self, "luma_accent_soft", "rgba(47,111,222,0.14)")
        bad = _rgba(self, "luma_destructive", "#c0392b")
        font = self.get_pango_context().get_font_description().copy()
        hv, vv = self.hadj.get_value(), self.vadj.get_value()
        r_first = int(vv // self.row_h)
        r_last = min(self.n_rows - 1, int((vv + h - self.head_h) // self.row_h) + 1)
        c_first = self.col_at(hv)
        c_last = min(self.n_cols - 1, self.col_at(hv + w - HEADER_W) + 1)
        sr1, sc1, sr2, sc2 = self.selection()

        def set_c(c):
            cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)

        cr.save()
        cr.rectangle(HEADER_W, self.head_h, w - HEADER_W, h - self.head_h)
        cr.clip()
        # selection fill
        if (sr1, sc1) != (sr2, sc2):
            x1 = HEADER_W + self.col_x(sc1) - hv
            y1 = self.head_h + sr1 * self.row_h - vv
            x2 = HEADER_W + self.col_x(sc2 + 1) - hv
            y2 = self.head_h + (sr2 + 1) * self.row_h - vv
            set_c(soft)
            cr.rectangle(x1, y1, x2 - x1, y2 - y1)
            cr.fill()
        # grid lines
        set_c(line)
        cr.set_line_width(1)
        for r in range(r_first, r_last + 2):
            y = self.head_h + r * self.row_h - vv + 0.5
            cr.move_to(HEADER_W, y)
            cr.line_to(w, y)
        x = HEADER_W + self.col_x(c_first) - hv
        for c in range(c_first, c_last + 2):
            cr.move_to(int(x) + 0.5, self.head_h)
            cr.line_to(int(x) + 0.5, h)
            x += self.col_w(c)
        cr.stroke()
        # cells: text overflows into empty neighbours to the right, like every spreadsheet
        for r in range(r_first, r_last + 1):
            for c in range(c_first, c_last + 1):
                info = self.cells.get(f"{r},{c}")
                if not info or info.get("v", "") == "":
                    continue
                val = self.value(r, c)
                text = formula.display(val, info.get("fmt", "general"))
                if not text:
                    continue
                x, y, cw, ch = self.cell_rect(r, c)
                numeric = isinstance(val, float)
                align = info.get("align") or ("end" if numeric or isinstance(val, bool) else "start")
                avail = cw
                if align == "start" and not numeric:
                    nc = c + 1
                    while nc <= c_last + 20 and not self.cells.get(f"{r},{nc}", {}).get("v"):
                        avail += self.col_w(nc)
                        nc += 1
                        if avail > 1200:
                            break
                lay = PangoCairo.create_layout(cr)
                fd = font.copy()
                if info.get("b"):
                    fd.set_weight(Pango.Weight.BOLD)
                if info.get("i"):
                    fd.set_style(Pango.Style.ITALIC)
                lay.set_font_description(fd)
                lay.set_text(text.replace("\n", " "), -1)
                lay.set_width(int((avail - 12) * Pango.SCALE))
                lay.set_ellipsize(Pango.EllipsizeMode.END)
                lay.set_alignment({"start": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
                                   "end": Pango.Alignment.RIGHT}[align])
                if align != "start":
                    lay.set_width(int((cw - 12) * Pango.SCALE))
                _, logical = lay.get_pixel_extents()
                set_c(bad if isinstance(val, formula.Error) else ink)
                cr.move_to(x + 6, y + (ch - logical.height) / 2)
                PangoCairo.show_layout(cr, lay)
        # current cell ring and selection outline
        set_c(accent)
        x1 = HEADER_W + self.col_x(sc1) - hv
        y1 = self.head_h + sr1 * self.row_h - vv
        x2 = HEADER_W + self.col_x(sc2 + 1) - hv
        y2 = self.head_h + (sr2 + 1) * self.row_h - vv
        cr.set_line_width(2)
        cr.rectangle(x1 + 1, y1 + 1, x2 - x1 - 1, y2 - y1 - 1)
        cr.stroke()
        cr.restore()

        # headers
        set_c(fill)
        cr.rectangle(0, 0, w, self.head_h)
        cr.rectangle(0, self.head_h, HEADER_W, h - self.head_h)
        cr.fill()
        small = font.copy()
        small.set_size(int(small.get_size() * 0.85))
        cr.save()
        cr.rectangle(HEADER_W, 0, w - HEADER_W, self.head_h)
        cr.clip()
        x = HEADER_W + self.col_x(c_first) - hv
        for c in range(c_first, c_last + 1):
            cw = self.col_w(c)
            on = sc1 <= c <= sc2
            lay = PangoCairo.create_layout(cr)
            fd = small.copy()
            if on:
                fd.set_weight(Pango.Weight.BOLD)
            lay.set_font_description(fd)
            lay.set_text(formula.col_name(c), -1)
            _, lg = lay.get_pixel_extents()
            set_c(accent if on else muted)
            cr.move_to(x + (cw - lg.width) / 2, (self.head_h - lg.height) / 2)
            PangoCairo.show_layout(cr, lay)
            set_c(line)
            cr.move_to(int(x + cw) + 0.5, 6)
            cr.line_to(int(x + cw) + 0.5, self.head_h - 6)
            cr.stroke()
            x += cw
        cr.restore()
        cr.save()
        cr.rectangle(0, self.head_h, HEADER_W, h - self.head_h)
        cr.clip()
        for r in range(r_first, r_last + 1):
            on = sr1 <= r <= sr2
            y = self.head_h + r * self.row_h - vv
            lay = PangoCairo.create_layout(cr)
            fd = small.copy()
            if on:
                fd.set_weight(Pango.Weight.BOLD)
            lay.set_font_description(fd)
            lay.set_text(str(r + 1), -1)
            _, lg = lay.get_pixel_extents()
            set_c(accent if on else muted)
            cr.move_to(HEADER_W - 8 - lg.width, y + (self.row_h - lg.height) / 2)
            PangoCairo.show_layout(cr, lay)
        cr.restore()

    # ------------------------------------------------------------ menus for the bar
    def format_rows(self, on_done=None):
        r, c = self.cur
        cur = self.info(r, c).get("fmt", "general")

        def pick(f):
            self.set_format(f)
            if on_done:
                on_done()
        return [MenuItem(label, selected=(f == cur), on_activate=lambda f=f: pick(f)) for f, label in FORMAT_NAMES.items()]

    def align_rows(self):
        cur = self.info(*self.cur).get("align")
        names = {None: ("text-align-start", "Automatic"), "start": ("text-align-start", "Left"),
                 "center": ("text-align-center", "Center"), "end": ("text-align-end", "Right")}
        return [MenuItem(label, icon=icon, selected=(a == cur), on_activate=lambda a=a: self.set_align(a))
                for a, (icon, label) in names.items()]


def _shift_block(raw: str, axis: int, at: int, delta: int) -> str:
    """Adjust references for inserted/deleted rows or columns (only refs at or past `at` move)."""
    import re
    pat = re.compile(r"(\"(?:[^\"]|\"\")*\")|(\$?)([A-Za-z]{1,2})(\$?)(\d{1,6})(?![\w(!])")

    def sub(m):
        if m.group(1):
            return m.group(1)
        dcol, col, drow, row = m.group(2), m.group(3), m.group(4), m.group(5)
        if col.upper() in ("TRUE", "FALSE"):
            return m.group(0)
        r, c = int(row) - 1, formula.col_index(col)
        pos = r if axis == 0 else c
        if pos >= at:
            if delta < 0 and pos < at - delta:
                return "#REF!"
            pos += delta
        r, c = (pos, c) if axis == 0 else (r, pos)
        return f"{dcol}{formula.col_name(c)}{drow}{r + 1}"
    return pat.sub(sub, raw)
