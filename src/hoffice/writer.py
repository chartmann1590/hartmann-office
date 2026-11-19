# SPDX-License-Identifier: GPL-3.0-or-later
"""Documents: a word processor page built on Gtk.TextView.

The page is our content; everything around it (the bar, the formatting
bubble, menus, toasts) is LumaUI. Paragraph kinds (title, headings, lists,
quote), alignment and inline marks (bold, italic, underline, strikethrough)
map one to one onto the OpenDocument model in odf.py.
"""
from __future__ import annotations

import datetime as dt

from gi.repository import Adw, GLib, GObject, Gtk, Pango

from luma_appkit import BarAction, BarMenu, ScrollView, SelectionBubble, SEPARATOR, apply_type
from luma_appkit.action_bubble import MenuItem

from . import odf

__all__ = ["Writer", "STYLE_NAMES"]

STYLE_NAMES = {"p": "Body", "title": "Title", "h1": "Heading 1", "h2": "Heading 2", "h3": "Heading 3",
               "quote": "Quote", "bullet": "Bulleted list", "number": "Numbered list"}
MARKS = {"b": ("bold", "Bold", ("Ctrl", "B")), "i": ("italic", "Italic", ("Ctrl", "I")),
         "u": ("underline", "Underline", ("Ctrl", "U")), "s": ("strikethrough", "Strikethrough", ())}
ALIGN_NAMES = {"start": ("text-align-start", "Align left"), "center": ("text-align-center", "Center"),
               "end": ("text-align-end", "Align right"), "justify": ("align-justify", "Justify")}
LIST_KINDS = ("bullet", "number")


class Writer(Gtk.Box):
    """One open document. Emits `changed` after every edit, for autosave and the word count."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, model: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.add_css_class("hoffice-writer")
        self.page_size = model.get("page", "letter")
        self.pending: dict[str, bool] = {}
        self._loading = False
        self._renumber_id = 0

        self.buffer = Gtk.TextBuffer(enable_undo=True)
        self._make_tags()
        self.view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, vexpand=True,
                                 left_margin=24, right_margin=24, top_margin=32, bottom_margin=140, pixels_below_lines=2)
        self.view.add_css_class("hoffice-page")
        self.view.update_property([Gtk.AccessibleProperty.LABEL], ["Document text"])
        apply_type(self.view, "body")
        # A readable measure: up to 760 px of text, centred (Notes' page does the same with a clamp).
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=560, child=self.view)
        self.scroll = ScrollView(clamp, vexpand=True)
        self.append(self.scroll)

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key)
        self.view.add_controller(keys)
        self.buffer.connect("insert-text", self._inserting)
        self.buffer.connect_after("insert-text", self._inserted)
        self.buffer.connect("changed", self._changed)
        self.buffer.connect("mark-set", self._mark_set)

        self.style_menu = BarMenu("Body", self._style_rows, name="Paragraph style")
        self.bubble = SelectionBubble(self.view, [BarMenu("Text", self._style_rows, name="Paragraph style"), SEPARATOR] + [
            BarAction(icon, tooltip=label, on_activate=lambda m=m: self.toggle_mark(m))
            for m, (icon, label, _k) in MARKS.items()])
        self.set_model(model)

    # ------------------------------------------------------------ tags
    def _make_tags(self):
        t = self.buffer.create_tag
        t("b", weight=Pango.Weight.BOLD)
        t("i", style=Pango.Style.ITALIC)
        t("u", underline=Pango.Underline.SINGLE)
        t("s", strikethrough=True)
        t("k:title", scale=2.2, weight=Pango.Weight.BOLD, pixels_below_lines=14)
        t("k:h1", scale=1.7, weight=Pango.Weight.BOLD, pixels_above_lines=18, pixels_below_lines=6)
        t("k:h2", scale=1.4, weight=Pango.Weight.BOLD, pixels_above_lines=14, pixels_below_lines=4)
        t("k:h3", scale=1.15, weight=Pango.Weight.BOLD, pixels_above_lines=10, pixels_below_lines=2)
        t("k:quote", style=Pango.Style.ITALIC, left_margin=36, pixels_above_lines=4, pixels_below_lines=4)
        t("k:bullet", left_margin=30, indent=-20)
        t("k:number", left_margin=30, indent=-20)
        t("k:p", pixels_below_lines=6)
        t("marker", editable=False)
        # The last paragraph ends in a hidden newline, so even an empty last line has a character
        # to carry its paragraph style (GTK tags need at least one character).
        t("sentinel", editable=False, invisible=True)
        t("a:center", justification=Gtk.Justification.CENTER)
        t("a:end", justification=Gtk.Justification.RIGHT)
        t("a:justify", justification=Gtk.Justification.FILL)
        self.tags = self.buffer.get_tag_table()

    def _line_bounds(self, line: int):
        start = self.buffer.get_iter_at_line(line)[1]
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return start, end

    def line_kind(self, line: int) -> str:
        start = self.buffer.get_iter_at_line(line)[1]
        for k in odf.BLOCK_KINDS:
            if start.has_tag(self.tags.lookup("k:" + k)):
                return k
        return "p"

    def line_align(self, line: int) -> str:
        start = self._marker_end(line)
        for a in ("center", "end", "justify"):
            if start.has_tag(self.tags.lookup("a:" + a)):
                return a
        return "start"

    def _marker_end(self, line: int):
        """The iter after a list marker ("• " / "3. "), or the line start."""
        it = self.buffer.get_iter_at_line(line)[1]
        marker = self.tags.lookup("marker")
        if it.has_tag(marker):
            it.forward_to_tag_toggle(marker)
        return it

    def _apply_line(self, line: int, kind: str | None = None, align: str | None = None):
        start, end = self._line_bounds(line)
        end2 = end.copy()
        end2.forward_char()  # the newline carries the paragraph's spacing too
        if kind is not None:
            old = self.line_kind(line)
            for k in odf.BLOCK_KINDS:
                self.buffer.remove_tag_by_name("k:" + k, start, end2)
            if old in LIST_KINDS and kind not in LIST_KINDS:
                self._remove_marker(line)
            start, end = self._line_bounds(line)
            end2 = end.copy()
            end2.forward_char()
            self.buffer.apply_tag_by_name("k:" + kind, start, end2)
            if kind in LIST_KINDS and old not in LIST_KINDS:
                self._insert_marker(line, "• ")
        if align is not None:
            start, end = self._line_bounds(line)
            end2 = end.copy()
            end2.forward_char()
            for a in ("center", "end", "justify"):
                self.buffer.remove_tag_by_name("a:" + a, start, end2)
            if align != "start":
                self.buffer.apply_tag_by_name("a:" + align, start, end2)

    def _insert_marker(self, line: int, text: str):
        # GTK takes a paragraph's justification and margins from its first character: the marker
        # carries the line's kind and alignment.
        kind, align = self.line_kind(line), self.line_align(line)
        it = self.buffer.get_iter_at_line(line)[1]
        tags = ["marker", "k:" + kind] + (["a:" + align] if align != "start" else [])
        self._loading, was = True, self._loading
        self.buffer.insert_with_tags_by_name(it, text, *tags)
        self._loading = was

    def _remove_marker(self, line: int):
        start = self.buffer.get_iter_at_line(line)[1]
        end = self._marker_end(line)
        if not start.equal(end):
            self._loading, was = True, self._loading
            self.buffer.delete(start, end)
            self._loading = was

    def _renumber(self):
        self._renumber_id = 0
        n = 0
        self.buffer.begin_irreversible_action()
        for line in range(self._lines()):
            kind = self.line_kind(line)
            if kind == "number":
                n += 1
                want = f"{n}. "
            elif kind == "bullet":
                n = 0
                want = "• "
            else:
                n = 0
                continue
            start = self.buffer.get_iter_at_line(line)[1]
            end = self._marker_end(line)
            if self.buffer.get_text(start, end, True) != want:
                align = self.line_align(line)
                self._remove_marker(line)
                self._insert_marker(line, want)
                if align != "start":
                    self._apply_line(line, align=align)
        self.buffer.end_irreversible_action()
        return False

    def _queue_renumber(self):
        if not self._renumber_id:
            self._renumber_id = GLib.idle_add(self._renumber)

    # ------------------------------------------------------------ model in and out
    def set_model(self, model: dict):
        self._loading = True
        self.buffer.begin_irreversible_action()
        self.buffer.set_text("")
        self.page_size = model.get("page", "letter")
        blocks = model.get("blocks") or odf.new_model("document")["blocks"]
        for i, b in enumerate(blocks):
            if i:
                self.buffer.insert(self.buffer.get_end_iter(), "\n")
            for r in b.get("runs", []):
                tags = [k for k in "bius" if r.get(k)]
                text = r.get("text", "")
                if text:
                    self.buffer.insert_with_tags_by_name(self.buffer.get_end_iter(), text, *tags)
        for i, b in enumerate(blocks):
            kind = b.get("kind", "p")
            start, end = self._line_bounds(i)
            end.forward_char()
            self.buffer.apply_tag_by_name("k:" + kind, start, end)
            if kind in LIST_KINDS:
                self._insert_marker(i, "• ")
            if b.get("align", "start") != "start":
                self._apply_line(i, align=b["align"])
        last = len(blocks) - 1
        end = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end, "\n", "sentinel", "k:" + blocks[last].get("kind", "p"))
        self._renumber()
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.buffer.end_irreversible_action()
        self._loading = False

    def _lines(self) -> int:
        """Paragraph count, without the empty line after the hidden sentinel."""
        return max(1, self.buffer.get_line_count() - 1)

    def model(self) -> dict:
        blocks = []
        marker = self.tags.lookup("marker")
        for line in range(self._lines()):
            start, end = self._line_bounds(line)
            runs = []
            it = start.copy()
            while it.compare(end) < 0:
                nxt = it.copy()
                if not nxt.forward_to_tag_toggle(None) or nxt.compare(end) > 0:
                    nxt = end.copy()
                if not it.has_tag(marker):
                    text = self.buffer.get_text(it, nxt, True)
                    marks = {k: True for k in "bius" if it.has_tag(self.tags.lookup(k))}
                    if text:
                        if runs and {k: runs[-1].get(k, False) for k in "bius"} == {k: marks.get(k, False) for k in "bius"}:
                            runs[-1]["text"] += text
                        else:
                            runs.append({"text": text, **marks})
                it = nxt
            blocks.append({"kind": self.line_kind(line), "align": self.line_align(line), "runs": runs or [{"text": ""}]})
        return {"kind": "document", "version": odf.MODEL_VERSION, "page": self.page_size, "blocks": blocks}

    def words(self) -> int:
        start, end = self.buffer.get_bounds()
        text = self.buffer.get_text(start, end, False)
        text = " ".join(t for t in text.split() if not (t == "•" or (t.endswith(".") and t[:-1].isdigit())))
        return len([w for w in text.split() if any(ch.isalnum() for ch in w)])

    # ------------------------------------------------------------ editing
    def _inserting(self, buf, where, text, length):
        # The paragraph's style, read before the new text takes the line's first character.
        line = where.get_line()
        self._pre = (self.line_kind(line), self.line_align(line))

    def _inserted(self, buf, end_iter, text, length):
        if self._loading:
            return
        start = end_iter.copy()
        start.backward_chars(len(text))
        # Inline marks: what was toggled with nothing selected, else what the text before had.
        before = start.copy()
        have = {}
        if self.pending:
            have = dict(self.pending)
        elif before.backward_char():
            have = {k: before.has_tag(self.tags.lookup(k)) for k in "bius"}
        for k, on in have.items():
            (buf.apply_tag_by_name if on else buf.remove_tag_by_name)(k, start, end_iter)
        buf.remove_tag_by_name("marker", start, end_iter)
        buf.remove_tag_by_name("sentinel", start, end_iter)
        # The paragraph's kind and alignment cover every line the insert touched.
        first, last = start.get_line(), end_iter.get_line()
        kind, align = getattr(self, "_pre", None) or (self.line_kind(first), self.line_align(first))
        if "\n" in text and kind in LIST_KINDS:
            pass
        for line in range(first, last + 1):
            s, e = self._line_bounds(line)
            e.forward_char()
            for k in odf.BLOCK_KINDS:
                if k != kind:
                    buf.remove_tag_by_name("k:" + k, s, e)
            buf.apply_tag_by_name("k:" + kind, s, e)
            for a in ("center", "end", "justify"):
                (buf.apply_tag_by_name if a == align else buf.remove_tag_by_name)("a:" + a, s, e)

    def _changed(self, _buf):
        if not self._loading:
            self.emit("changed")

    def _mark_set(self, _buf, _iter, mark):
        if mark.get_name() == "insert":
            it = self.buffer.get_iter_at_mark(mark)
            if it.is_end() and self.buffer.get_char_count() > 0:  # never past the hidden sentinel
                it.backward_char()
                self.buffer.place_cursor(it)
                return
            self.pending = {}
            line = self.buffer.get_iter_at_mark(mark).get_line()
            self.style_menu_label(STYLE_NAMES[self.line_kind(line)])
            it = self.buffer.get_iter_at_mark(mark)
            if it.has_tag(self.tags.lookup("marker")):
                it.forward_to_tag_toggle(self.tags.lookup("marker"))
                self.buffer.place_cursor(it)

    def style_menu_label(self, text: str):
        label = getattr(self.style_menu, "_text", None)
        if label is not None:
            label.set_label(text)

    def _key(self, _ctl, keyval, _code, state):
        from gi.repository import Gdk
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and not shift and keyval in (Gdk.KEY_b, Gdk.KEY_i, Gdk.KEY_u):
            self.toggle_mark({Gdk.KEY_b: "b", Gdk.KEY_i: "i", Gdk.KEY_u: "u"}[keyval])
            return True
        if ctrl and keyval == Gdk.KEY_z:
            (self.buffer.redo if shift else self.buffer.undo)()
            self._queue_renumber()
            return True
        if ctrl and keyval == Gdk.KEY_y:
            self.buffer.redo()
            self._queue_renumber()
            return True
        if ctrl and keyval in (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3, Gdk.KEY_0) and not shift:
            self.set_kind({Gdk.KEY_1: "h1", Gdk.KEY_2: "h2", Gdk.KEY_3: "h3", Gdk.KEY_0: "p"}[keyval])
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift:
            it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
            line = it.get_line()
            kind = self.line_kind(line)
            start, end = self._line_bounds(line)
            body = self.buffer.get_text(self._marker_end(line), end, True)
            if kind in LIST_KINDS and not body.strip():
                self.set_kind("p")  # Return on an empty list item ends the list
                return True
            if kind in ("title", "h1", "h2", "h3") and it.ends_line():
                self.buffer.insert_at_cursor("\n")
                self._apply_line(line + 1, kind="p")
                return True
            if kind in LIST_KINDS:
                self.buffer.insert_at_cursor("\n")
                new = line + 1
                self._insert_marker(new, "• ")
                self._queue_renumber()
                return True
        if keyval == Gdk.KEY_BackSpace and not self.buffer.get_has_selection():
            it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
            line = it.get_line()
            if self.line_kind(line) in LIST_KINDS and it.equal(self._marker_end(line)):
                self.set_kind("p")
                return True
        return False

    def selection_or_word(self):
        if self.buffer.get_has_selection():
            return self.buffer.get_selection_bounds()
        return None

    def toggle_mark(self, mark: str):
        sel = self.selection_or_word()
        tag = self.tags.lookup(mark)
        if sel:
            start, end = sel
            it, every = start.copy(), True
            while it.compare(end) < 0:
                if not it.has_tag(tag) and not it.has_tag(self.tags.lookup("marker")):
                    every = False
                    break
                it.forward_char()
            (self.buffer.remove_tag if every else self.buffer.apply_tag)(tag, start, end)
            self.emit("changed")
        else:
            it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
            before = it.copy()
            now = before.backward_char() and before.has_tag(tag)
            base = self.pending or {k: (before.has_tag(self.tags.lookup(k)) if it.get_offset() else False) for k in "bius"}
            base = dict(base)
            base[mark] = not base.get(mark, now)
            self.pending = base
        self.view.grab_focus()

    def mark_active(self, mark: str) -> bool:
        if mark in self.pending:
            return self.pending[mark]
        it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        if self.buffer.get_has_selection():
            it = self.buffer.get_selection_bounds()[0]
        else:
            it.backward_char()
        return it.has_tag(self.tags.lookup(mark))

    def _selected_lines(self):
        if self.buffer.get_has_selection():
            a, b = self.buffer.get_selection_bounds()
            return range(a.get_line(), b.get_line() + 1)
        line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        return range(line, line + 1)

    def set_kind(self, kind: str):
        lines = list(self._selected_lines())
        target = kind
        if kind in LIST_KINDS and all(self.line_kind(x) == kind for x in lines):
            target = "p"  # the list button turns a list back into body text
        for line in lines:
            self._apply_line(line, kind=target)
        self._renumber()
        self.style_menu_label(STYLE_NAMES[target])
        self.emit("changed")
        self.view.grab_focus()

    def set_align(self, align: str):
        for line in self._selected_lines():
            self._apply_line(line, align=align)
        self.emit("changed")
        self.view.grab_focus()

    def current_kind(self) -> str:
        return self.line_kind(self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line())

    def current_align(self) -> str:
        return self.line_align(self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line())

    def insert_text(self, text: str):
        self.buffer.insert_at_cursor(text)
        self.view.grab_focus()

    def insert_date(self):
        self.insert_text(dt.date.today().strftime("%B %-d, %Y"))

    def undo(self):
        self.buffer.undo()
        self._queue_renumber()

    def redo(self):
        self.buffer.redo()
        self._queue_renumber()

    # ------------------------------------------------------------ menus for the bar
    def _style_rows(self):
        cur = self.current_kind()
        return [MenuItem(STYLE_NAMES[k], icon={"p": "pilcrow", "title": "type", "h1": "heading", "h2": "heading",
                                                "h3": "heading", "quote": "quote", "bullet": "list",
                                                "number": "list-ordered"}[k],
                         selected=(k == cur), on_activate=lambda k=k: self.set_kind(k))
                for k in ("p", "title", "h1", "h2", "h3", "quote", "bullet", "number")]

    def align_rows(self):
        cur = self.current_align()
        return [MenuItem(label, icon=icon, selected=(a == cur), on_activate=lambda a=a: self.set_align(a))
                for a, (icon, label) in ALIGN_NAMES.items()]

    def find(self, text: str) -> bool:
        """Select the next match after the cursor (wrapping); False when there is none."""
        if not text:
            return False
        it = self.buffer.get_iter_at_mark(self.buffer.get_selection_bound())
        flags = Gtk.TextSearchFlags.CASE_INSENSITIVE | Gtk.TextSearchFlags.TEXT_ONLY
        found = it.forward_search(text, flags, None) or self.buffer.get_start_iter().forward_search(text, flags, None)
        if not found:
            return False
        a, b = found
        self.buffer.select_range(a, b)
        self.view.scroll_to_iter(a, 0.2, False, 0, 0)
        return True

    def replace_all(self, find: str, repl: str) -> int:
        if not find:
            return 0
        n = 0
        it = self.buffer.get_start_iter()
        flags = Gtk.TextSearchFlags.CASE_INSENSITIVE | Gtk.TextSearchFlags.TEXT_ONLY
        self.buffer.begin_user_action()
        while True:
            found = it.forward_search(find, flags, None)
            if not found:
                break
            a, b = found
            mark = self.buffer.create_mark(None, b, False)
            self.buffer.delete(a, b)
            a = self.buffer.get_iter_at_mark(mark)
            self.buffer.insert(a, repl)
            it = self.buffer.get_iter_at_mark(mark)
            self.buffer.delete_mark(mark)
            n += 1
        self.buffer.end_user_action()
        return n
