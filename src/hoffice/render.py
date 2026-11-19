# SPDX-License-Identifier: GPL-3.0-or-later
"""Pages: laying documents, spreadsheets and slides out for PDF and printing.

Each layout takes a model and a page size in points, splits it into pages,
and draws page N on any cairo context, so the PDF export and the print
dialog share one renderer. Slides are also drawn on screen with draw_slide.
Page content uses the document's own colours (a page is paper); the app's
interface uses LumaUI tokens.
"""
from __future__ import annotations

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
import cairo  # noqa: E402
from gi.repository import Pango, PangoCairo  # noqa: E402

from . import formula, odf  # noqa: E402

__all__ = ["PAGE_SIZES", "DocumentLayout", "SheetLayout", "SlideLayout", "draw_slide", "THEMES", "write_pdf"]

PAGE_SIZES = {"letter": (612.0, 792.0), "a4": (595.28, 841.89)}
SLIDE_SIZE = (960.0, 540.0)
FONT = "Figtree, Cantarell, Liberation Sans, sans-serif"

# kind -> (size pt, weight, space before, space after, italic)
_BLOCK = {"p": (11, 400, 0, 7, False), "title": (26, 700, 0, 12, False), "h1": (20, 700, 12, 6, False),
          "h2": (16, 700, 10, 5, False), "h3": (13, 700, 8, 4, False), "bullet": (11, 400, 0, 4, False),
          "number": (11, 400, 0, 4, False), "quote": (11, 400, 4, 8, True)}
_ALIGN = {"start": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER, "end": Pango.Alignment.RIGHT,
          "justify": Pango.Alignment.LEFT}


def _markup(runs) -> str:
    out = []
    for r in runs:
        t = GLib_escape(r.get("text", ""))
        if r.get("b"):
            t = f"<b>{t}</b>"
        if r.get("i"):
            t = f"<i>{t}</i>"
        if r.get("u"):
            t = f"<u>{t}</u>"
        if r.get("s"):
            t = f"<s>{t}</s>"
        out.append(t)
    return "".join(out) or " "


def GLib_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DocumentLayout:
    """Paragraphs flowed onto pages with 1 inch margins; lines never split across a page break mid-line."""

    def __init__(self, model: dict, page: tuple[float, float] | None = None):
        self.model = model
        self.size = page or PAGE_SIZES.get(model.get("page", "letter"), PAGE_SIZES["letter"])
        self.margin = 72.0
        self._pages = None

    def _layouts(self, cr):
        w = self.size[0] - 2 * self.margin
        items, n = [], 0
        for b in self.model["blocks"]:
            k = b.get("kind", "p")
            size, weight, before, after, italic = _BLOCK.get(k, _BLOCK["p"])
            lay = PangoCairo.create_layout(cr)
            fd = Pango.FontDescription.from_string(FONT)
            fd.set_size(int(size * Pango.SCALE))
            fd.set_weight(Pango.Weight(weight))
            if italic:
                fd.set_style(Pango.Style.ITALIC)
            lay.set_font_description(fd)
            indent = 0.0
            prefix = ""
            n = n + 1 if k == "number" else 0
            if k == "bullet":
                prefix, indent = "•\t", 18.0
            elif k == "number":
                prefix, indent = f"{n}.\t", 18.0
            elif k == "quote":
                indent = 28.0
            lay.set_width(int((w - indent) * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            lay.set_alignment(_ALIGN.get(b.get("align", "start"), Pango.Alignment.LEFT))
            lay.set_justify(b.get("align") == "justify")
            lay.set_spacing(int(size * 0.35 * Pango.SCALE))
            if prefix:
                tabs = Pango.TabArray.new(1, True)
                tabs.set_tab(0, Pango.TabAlign.LEFT, int(indent))
                lay.set_tabs(tabs)
                lay.set_indent(int(-indent * Pango.SCALE))
                lay.set_width(int(w * Pango.SCALE))
                indent = 0.0
                lay.set_markup(GLib_escape(prefix) + _markup(b.get("runs", [])), -1)
                indent_x = 18.0
            else:
                lay.set_markup(_markup(b.get("runs", [])), -1)
                indent_x = indent
            items.append((lay, indent_x, before, after))
        return items

    def paginate(self, cr):
        top, bottom = self.margin, self.size[1] - self.margin
        pages, cur, y = [], [], top
        for lay, x, before, after in self._layouts(cr):
            y += before if cur else 0
            it = lay.get_iter()
            while True:
                line = it.get_line_readonly()
                ink, logical = it.get_line_extents()
                lh = logical.height / Pango.SCALE
                if y + lh > bottom and cur:
                    pages.append(cur)
                    cur, y = [], top
                baseline = it.get_baseline() / Pango.SCALE
                line_top = logical.y / Pango.SCALE
                cur.append((line, self.margin + x + logical.x / Pango.SCALE, y + (baseline - line_top)))
                y += lh + lay.get_spacing() / Pango.SCALE
                if not it.next_line():
                    break
            y += after
        pages.append(cur)
        self._pages = pages
        return len(pages)

    def draw(self, cr, index: int):
        cr.set_source_rgb(0.1, 0.1, 0.1)
        for line, x, y in self._pages[index]:
            cr.move_to(x, y)
            PangoCairo.show_layout_line(cr, line)


class SheetLayout:
    """The used part of one sheet as a ruled table, split into pages across and down."""

    def __init__(self, model: dict, sheet: int = 0, page: tuple[float, float] | None = None):
        self.model, self.sheet = model, sheet
        self.size = page or PAGE_SIZES["letter"]
        self.margin = 40.0
        self.wb = formula.Workbook()
        for s in model["sheets"]:
            self.wb.add_sheet(s["name"], {tuple(map(int, k.split(","))): v.get("v", "") for k, v in s["cells"].items()})
        self.cells = model["sheets"][sheet]["cells"]
        self.widths = model["sheets"][sheet].get("widths", {})
        self.rows, self.cols = self.wb.extent(sheet)
        self.row_h = 18.0

    def col_w(self, c):
        return float(self.widths.get(str(c), 100)) * 0.75

    def paginate(self, cr=None):
        usable_w = self.size[0] - 2 * self.margin
        usable_h = self.size[1] - 2 * self.margin
        col_groups, cur, w = [], [], 0.0
        for c in range(self.cols):
            cw = self.col_w(c)
            if cur and w + cw > usable_w:
                col_groups.append(cur)
                cur, w = [], 0.0
            cur.append(c)
            w += cw
        col_groups.append(cur)
        per = max(1, int(usable_h // self.row_h))
        row_groups = [list(range(r, min(self.rows, r + per))) for r in range(0, self.rows, per)] or [[0]]
        self._pages = [(rg, cg) for rg in row_groups for cg in col_groups]
        return len(self._pages)

    def draw(self, cr, index: int):
        rows, cols = self._pages[index]
        fd = Pango.FontDescription.from_string(FONT)
        fd.set_size(int(9 * Pango.SCALE))
        y = self.margin
        for r in rows:
            x = self.margin
            for c in cols:
                cw = self.col_w(c)
                cr.set_source_rgb(0.82, 0.82, 0.82)
                cr.set_line_width(0.5)
                cr.rectangle(x, y, cw, self.row_h)
                cr.stroke()
                info = self.cells.get(f"{r},{c}")
                if info:
                    val = self.wb.value(self.sheet, r, c)
                    text = formula.display(val, info.get("fmt", "general"))
                    lay = PangoCairo.create_layout(cr)
                    f2 = fd.copy()
                    if info.get("b"):
                        f2.set_weight(Pango.Weight.BOLD)
                    if info.get("i"):
                        f2.set_style(Pango.Style.ITALIC)
                    lay.set_font_description(f2)
                    lay.set_text(text, -1)
                    lay.set_width(int((cw - 6) * Pango.SCALE))
                    lay.set_ellipsize(Pango.EllipsizeMode.END)
                    numeric = isinstance(val, float) and not isinstance(val, bool)
                    al = info.get("align") or ("end" if numeric else "start")
                    lay.set_alignment(_ALIGN[al])
                    cr.set_source_rgb(0.1, 0.1, 0.1)
                    _, logical = lay.get_pixel_extents()
                    cr.move_to(x + 3, y + (self.row_h - logical.height) / 2)
                    PangoCairo.show_layout(cr, lay)
                x += cw
            y += self.row_h


# ---------------------------------------------------------------- slides
# name -> (background, ink, accent, label). Content colours: a slide is the
# presenter's page, like paper, not the app's interface.
THEMES = {
    "paper": ((0.984, 0.973, 0.945), (0.12, 0.114, 0.10), (0.80, 0.42, 0.20), "Paper"),
    "ink": ((0.09, 0.094, 0.11), (0.957, 0.949, 0.933), (0.55, 0.72, 1.0), "Ink"),
    "harbor": ((0.07, 0.227, 0.353), (0.949, 0.969, 0.984), (0.45, 0.82, 0.86), "Harbor"),
    "meadow": ((0.906, 0.945, 0.894), (0.114, 0.20, 0.125), (0.24, 0.55, 0.30), "Meadow"),
    "ember": ((0.227, 0.086, 0.063), (1.0, 0.945, 0.91), (1.0, 0.62, 0.35), "Ember"),
}


def _text(cr, text, x, y, w, h, size, weight=400, align=Pango.Alignment.LEFT, colour=(0, 0, 0), valign="top",
          fit=True):
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string(FONT)
    lay.set_width(int(w * Pango.SCALE))
    lay.set_wrap(Pango.WrapMode.WORD_CHAR)
    lay.set_alignment(align)
    while True:
        fd.set_absolute_size(size * Pango.SCALE)
        fd.set_weight(Pango.Weight(weight))
        lay.set_font_description(fd)
        lay.set_text(text, -1)
        _, logical = lay.get_pixel_extents()
        if not fit or logical.height <= h or size <= 10:
            break
        size *= 0.9
    oy = y if valign == "top" else y + (h - logical.height) / 2
    cr.set_source_rgb(*colour)
    cr.move_to(x, oy)
    PangoCairo.show_layout(cr, lay)
    return logical.height


def draw_slide(cr, width: float, height: float, slide: dict, theme: str = "paper", number: int | None = None):
    """Draw one slide scaled into width × height (any 16:9 box)."""
    bg, ink, accent, _ = THEMES.get(theme, THEMES["paper"])
    cr.save()
    cr.scale(width / SLIDE_SIZE[0], height / SLIDE_SIZE[1])
    W, H = SLIDE_SIZE
    cr.set_source_rgb(*bg)
    cr.rectangle(0, 0, W, H)
    cr.fill()
    lay = slide.get("layout", "content")
    title = slide.get("title", "")
    body = slide.get("body", "")
    if lay == "title":
        cr.set_source_rgb(*accent)
        cr.rectangle(72, H * 0.36, 64, 6)
        cr.fill()
        _text(cr, title, 72, H * 0.40, W - 144, H * 0.30, 56, 700, colour=ink)
        if body.strip():
            _text(cr, body, 72, H * 0.72, W - 144, H * 0.18, 24, 400, colour=tuple(c * 0.85 + b * 0.15 for c, b in zip(ink, bg)))
    elif lay == "section":
        _text(cr, title, 72, 0, W - 144, H, 48, 700, align=Pango.Alignment.CENTER, colour=ink, valign="middle")
        cr.set_source_rgb(*accent)
        cr.rectangle(W / 2 - 32, H * 0.66, 64, 6)
        cr.fill()
    elif lay == "content":
        th = _text(cr, title, 64, 48, W - 128, 110, 40, 700, colour=ink)
        cr.set_source_rgb(*accent)
        cr.rectangle(64, 48 + th + 14, 48, 5)
        cr.fill()
        y = 48 + th + 44
        for line in [x for x in body.split("\n") if x.strip()]:
            if y > H - 60:
                break
            depth = (len(line) - len(line.lstrip(" "))) // 2
            text = line.strip().lstrip("-•* ").strip()
            x = 72 + depth * 32
            cr.set_source_rgb(*accent)
            cr.arc(x + 6, y + 17, 5 if depth == 0 else 4, 0, 6.2832)
            cr.fill()
            y += _text(cr, text, x + 26, y, W - x - 96, H - y - 40, 28 if depth == 0 else 24, 400, colour=ink, fit=False) + 14
    if number is not None and lay != "title":
        _text(cr, str(number), W - 96, H - 44, 60, 24, 14, 500, align=Pango.Alignment.RIGHT,
              colour=tuple(c * 0.5 + b * 0.5 for c, b in zip(ink, bg)), fit=False)
    cr.restore()


class SlideLayout:
    def __init__(self, model: dict):
        self.model = model
        self.size = SLIDE_SIZE

    def paginate(self, cr=None):
        return len(self.model["slides"])

    def draw(self, cr, index: int):
        draw_slide(cr, self.size[0], self.size[1], self.model["slides"][index], self.model.get("theme", "paper"),
                   index + 1)


def layout_for(model: dict, sheet: int = 0):
    k = model["kind"]
    if k == "document":
        return DocumentLayout(model)
    if k == "spreadsheet":
        return SheetLayout(model, sheet)
    return SlideLayout(model)


def write_pdf(path: str, model: dict, title: str = "", sheet: int = 0) -> int:
    lay = layout_for(model, sheet)
    surface = cairo.PDFSurface(path, *lay.size)
    try:
        surface.set_metadata(cairo.PDFMetadata.TITLE, title)
        surface.set_metadata(cairo.PDFMetadata.CREATOR, "Hartmann Office")
    except (AttributeError, cairo.Error):
        pass
    cr = cairo.Context(surface)
    n = lay.paginate(cr)
    for i in range(n):
        lay.draw(cr, i)
        cr.show_page()
    surface.finish()
    return n
