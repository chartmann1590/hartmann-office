# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenDocument files: .odt (documents), .ods (spreadsheets), .odp (presentations).

Each editor keeps a plain model (dicts and lists, see `new_model`). Saving
writes a real OpenDocument package that LibreOffice, Microsoft Office and
Google Docs open, plus a copy of the model (`Hoffice/model.json`, listed in
the manifest) so our own files come back exactly. Opening a file someone else
made reads its content.xml: paragraphs, headings, lists and bold/italic/
underline for documents; values, formulas and sheets for spreadsheets; titles,
text and notes for presentations.
"""
from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from . import formula

__all__ = ["KINDS", "MIMETYPES", "new_model", "save", "load", "kind_for_path", "model_text",
           "csv_to_model", "model_to_csv", "text_to_model", "model_to_markdown"]

KINDS = ("document", "spreadsheet", "presentation")
EXT = {"document": ".odt", "spreadsheet": ".ods", "presentation": ".odp"}
MIMETYPES = {
    "document": "application/vnd.oasis.opendocument.text",
    "spreadsheet": "application/vnd.oasis.opendocument.spreadsheet",
    "presentation": "application/vnd.oasis.opendocument.presentation",
}
MODEL_PATH = "Hoffice/model.json"
MODEL_VERSION = 1

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "of": "urn:oasis:names:tc:opendocument:xmlns:of:1.2",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "dc": "http://purl.org/dc/elements/1.1/",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
}
_XMLNS = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items() if k != "manifest")


def q(tag: str) -> str:
    p, local = tag.split(":")
    return "{%s}%s" % (NS[p], local)


# ---------------------------------------------------------------- models
BLOCK_KINDS = ("p", "title", "h1", "h2", "h3", "bullet", "number", "quote")
ALIGNS = ("start", "center", "end", "justify")
THEMES = ("paper", "ink", "harbor", "meadow", "ember")
LAYOUTS = ("title", "content", "section", "blank")


def new_model(kind: str) -> dict:
    if kind == "document":
        return {"kind": kind, "version": MODEL_VERSION, "page": "letter",
                "blocks": [{"kind": "title", "align": "start", "runs": [{"text": ""}]}]}
    if kind == "spreadsheet":
        return {"kind": kind, "version": MODEL_VERSION, "sheets": [{"name": "Sheet 1", "cells": {}, "widths": {}}]}
    if kind == "presentation":
        return {"kind": kind, "version": MODEL_VERSION, "theme": "paper",
                "slides": [{"layout": "title", "title": "", "body": "", "notes": ""}]}
    raise ValueError(kind)


def kind_for_path(path: str) -> str | None:
    p = path.lower()
    if p.endswith((".odt", ".txt", ".md", ".markdown", ".fodt")):
        return "document"
    if p.endswith((".ods", ".csv", ".tsv")):
        return "spreadsheet"
    if p.endswith(".odp"):
        return "presentation"
    return None


def model_text(model: dict) -> str:
    """The words in a model, for search and the sidebar's preview line."""
    k = model.get("kind")
    if k == "document":
        return "\n".join("".join(r.get("text", "") for r in b.get("runs", [])) for b in model.get("blocks", []))
    if k == "spreadsheet":
        return " ".join(c.get("v", "") for s in model.get("sheets", []) for c in s.get("cells", {}).values())
    if k == "presentation":
        return "\n".join(f"{s.get('title', '')}\n{s.get('body', '')}" for s in model.get("slides", []))
    return ""


# ---------------------------------------------------------------- package
def _manifest(kind: str) -> str:
    entries = [("/", MIMETYPES[kind]), ("content.xml", "text/xml"), ("styles.xml", "text/xml"),
               ("meta.xml", "text/xml"), (MODEL_PATH, "application/json")]
    rows = "".join(f'<manifest:file-entry manifest:full-path="{p}" manifest:media-type="{t}"'
                   + (' manifest:version="1.3"' if p == "/" else "") + "/>" for p, t in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<manifest:manifest xmlns:manifest="{NS["manifest"]}" manifest:version="1.3">{rows}</manifest:manifest>')


def _meta(title: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-meta {_XMLNS} office:version="1.3"><office:meta>'
            f'<meta:generator>Hartmann Office</meta:generator><dc:title>{escape(title)}</dc:title>'
            '</office:meta></office:document-meta>')


def save(path_or_file, model: dict, title: str = "") -> None:
    kind = model["kind"]
    content, styles = {"document": _odt, "spreadsheet": _ods, "presentation": _odp}[kind](model)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), MIMETYPES[kind], compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/manifest.xml", _manifest(kind), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("styles.xml", styles, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("meta.xml", _meta(title), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(MODEL_PATH, json.dumps(model, ensure_ascii=False), compress_type=zipfile.ZIP_DEFLATED)
    data = buf.getvalue()
    if hasattr(path_or_file, "write"):
        path_or_file.write(data)
    else:
        with open(path_or_file, "wb") as f:
            f.write(data)


def load(path_or_bytes, name_hint: str = "") -> dict:
    """A model from an OpenDocument package, a CSV/TSV, or plain/Markdown text."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data, name = bytes(path_or_bytes), name_hint
    else:
        with open(path_or_bytes, "rb") as f:
            data = f.read()
        name = name_hint or str(path_or_bytes)
    low = name.lower()
    if low.endswith((".csv", ".tsv")):
        return csv_to_model(data.decode("utf-8-sig", "replace"), "\t" if low.endswith(".tsv") else ",")
    if low.endswith((".txt", ".md", ".markdown")):
        return text_to_model(data.decode("utf-8-sig", "replace"), markdown=not low.endswith(".txt"))
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This file isn't an OpenDocument file.")
    with z:
        names = set(z.namelist())
        mime = z.read("mimetype").decode().strip() if "mimetype" in names else ""
        kind = next((k for k, m in MIMETYPES.items() if mime.startswith(m)), None)
        if kind is None:
            raise ValueError("This kind of OpenDocument file isn't supported.")
        if MODEL_PATH in names:
            try:
                model = json.loads(z.read(MODEL_PATH).decode())
                if model.get("kind") == kind and model.get("version", 0) <= MODEL_VERSION:
                    return _normalise(model)
            except (ValueError, KeyError):
                pass
        root = ET.fromstring(z.read("content.xml"))
        styles = ET.fromstring(z.read("styles.xml")) if "styles.xml" in names else None
    return _normalise({"document": _read_odt, "spreadsheet": _read_ods, "presentation": _read_odp}[kind](root, styles))


def _normalise(model: dict) -> dict:
    """Fill anything missing so editors can trust the model's shape."""
    base = new_model(model["kind"])
    for k, v in base.items():
        model.setdefault(k, copy.deepcopy(v))
    if model["kind"] == "document":
        if not model["blocks"]:
            model["blocks"] = copy.deepcopy(base["blocks"])
        for b in model["blocks"]:
            b.setdefault("kind", "p")
            b.setdefault("align", "start")
            b.setdefault("runs", [{"text": ""}])
            if b["kind"] not in BLOCK_KINDS:
                b["kind"] = "p"
    elif model["kind"] == "spreadsheet":
        if not model["sheets"]:
            model["sheets"] = copy.deepcopy(base["sheets"])
        for s in model["sheets"]:
            s.setdefault("cells", {})
            s.setdefault("widths", {})
            s.setdefault("name", "Sheet")
    else:
        if not model["slides"]:
            model["slides"] = copy.deepcopy(base["slides"])
        if model.get("theme") not in THEMES:
            model["theme"] = "paper"
        for s in model["slides"]:
            for k in ("title", "body", "notes"):
                s.setdefault(k, "")
            if s.get("layout") not in LAYOUTS:
                s["layout"] = "content"
    return model


# ---------------------------------------------------------------- .odt
_PARA_STYLE = {"p": "Text_20_body", "title": "Title", "h1": "Heading_20_1", "h2": "Heading_20_2",
               "h3": "Heading_20_3", "bullet": "List_20_Paragraph", "number": "List_20_Paragraph",
               "quote": "Quotations"}
_ALIGN_FO = {"start": "start", "center": "center", "end": "end", "justify": "justify"}


def _run_style(r) -> str | None:
    key = "".join(x for x in "bius" if r.get(x))
    return f"T_{key}" if key else None


def _odt(model):
    autos, used_runs, used_paras = [], set(), set()
    body = []
    open_list = None

    def close_list():
        nonlocal open_list
        if open_list:
            body.append("</text:list>")
            open_list = None

    for b in model["blocks"]:
        kind, align = b.get("kind", "p"), b.get("align", "start")
        pstyle = _PARA_STYLE[kind]
        if align != "start":
            name = f"P_{kind}_{align}"
            if name not in used_paras:
                used_paras.add(name)
                autos.append(f'<style:style style:name="{name}" style:family="paragraph" '
                             f'style:parent-style-name="{pstyle}"><style:paragraph-properties '
                             f'fo:text-align="{_ALIGN_FO[align]}"/></style:style>')
            pstyle = name
        spans = []
        for r in b.get("runs", []):
            t = escape(r.get("text", "")).replace("\t", "<text:tab/>")
            t = re.sub(r"  +", lambda m: " <text:s text:c=\"%d\"/>" % (len(m.group(0)) - 1), t)
            t = t.replace("\n", "<text:line-break/>")
            st = _run_style(r)
            if st:
                used_runs.add(st)
                spans.append(f'<text:span text:style-name="{st}">{t}</text:span>')
            else:
                spans.append(t)
        inner = "".join(spans)
        if kind in ("bullet", "number"):
            want = "L_bullet" if kind == "bullet" else "L_number"
            if open_list != want:
                close_list()
                body.append(f'<text:list text:style-name="{want}">')
                open_list = want
            body.append(f'<text:list-item><text:p text:style-name="{pstyle}">{inner}</text:p></text:list-item>')
            continue
        close_list()
        if kind in ("h1", "h2", "h3"):
            body.append(f'<text:h text:style-name="{pstyle}" text:outline-level="{kind[1]}">{inner}</text:h>')
        else:
            body.append(f'<text:p text:style-name="{pstyle}">{inner}</text:p>')
    close_list()
    for st in sorted(used_runs):
        k = st[2:]
        props = []
        if "b" in k:
            props.append('fo:font-weight="bold" style:font-weight-asian="bold" style:font-weight-complex="bold"')
        if "i" in k:
            props.append('fo:font-style="italic" style:font-style-asian="italic" style:font-style-complex="italic"')
        if "u" in k:
            props.append('style:text-underline-style="solid" style:text-underline-width="auto" '
                         'style:text-underline-color="font-color"')
        if "s" in k:
            props.append('style:text-line-through-style="solid"')
        autos.append(f'<style:style style:name="{st}" style:family="text"><style:text-properties {" ".join(props)}/>'
                     '</style:style>')
    lists = ('<text:list-style style:name="L_bullet"><text:list-level-style-bullet text:level="1" '
             'text:bullet-char="•"><style:list-level-properties text:list-level-position-and-space-mode='
             '"label-alignment"><style:list-level-label-alignment text:label-followed-by="listtab" '
             'text:list-tab-stop-position="0.25in" fo:text-indent="-0.25in" fo:margin-left="0.25in"/>'
             '</style:list-level-properties></text:list-level-style-bullet></text:list-style>'
             '<text:list-style style:name="L_number"><text:list-level-style-number text:level="1" '
             'style:num-suffix="." style:num-format="1"><style:list-level-properties '
             'text:list-level-position-and-space-mode="label-alignment"><style:list-level-label-alignment '
             'text:label-followed-by="listtab" text:list-tab-stop-position="0.25in" fo:text-indent="-0.25in" '
             'fo:margin-left="0.25in"/></style:list-level-properties></text:list-level-style-number></text:list-style>')
    content = ('<?xml version="1.0" encoding="UTF-8"?>'
               f'<office:document-content {_XMLNS} office:version="1.3">'
               f'<office:automatic-styles>{"".join(autos)}{lists}</office:automatic-styles>'
               f'<office:body><office:text>{"".join(body)}</office:text></office:body></office:document-content>')
    w, h = ("8.5in", "11in") if model.get("page", "letter") == "letter" else ("21cm", "29.7cm")
    styles = ('<?xml version="1.0" encoding="UTF-8"?>'
              f'<office:document-styles {_XMLNS} office:version="1.3"><office:styles>'
              '<style:default-style style:family="paragraph"><style:text-properties fo:font-size="11pt" '
              'style:font-name="Liberation Sans" fo:font-family="\'Liberation Sans\', Arial, sans-serif"/>'
              '</style:default-style>'
              '<style:style style:name="Standard" style:family="paragraph"/>'
              '<style:style style:name="Text_20_body" style:display-name="Text body" style:family="paragraph" '
              'style:parent-style-name="Standard"><style:paragraph-properties fo:margin-bottom="0.08in" '
              'fo:line-height="140%"/></style:style>'
              '<style:style style:name="Title" style:family="paragraph" style:parent-style-name="Standard">'
              '<style:paragraph-properties fo:margin-bottom="0.12in"/><style:text-properties fo:font-size="26pt" '
              'fo:font-weight="bold"/></style:style>'
              + "".join(f'<style:style style:name="Heading_20_{n}" style:display-name="Heading {n}" '
                        f'style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="{n}">'
                        f'<style:paragraph-properties fo:margin-top="0.16in" fo:margin-bottom="0.06in"/>'
                        f'<style:text-properties fo:font-size="{s}pt" fo:font-weight="bold"/></style:style>'
                        for n, s in ((1, 20), (2, 16), (3, 13)))
              + '<style:style style:name="List_20_Paragraph" style:display-name="List Paragraph" '
              'style:family="paragraph" style:parent-style-name="Text_20_body"/>'
              '<style:style style:name="Quotations" style:family="paragraph" style:parent-style-name="Text_20_body">'
              '<style:paragraph-properties fo:margin-left="0.4in" fo:margin-right="0.4in"/>'
              '<style:text-properties fo:font-style="italic"/></style:style>'
              '</office:styles><office:automatic-styles><style:page-layout style:name="PL1">'
              f'<style:page-layout-properties fo:page-width="{w}" fo:page-height="{h}" fo:margin-top="1in" '
              'fo:margin-bottom="1in" fo:margin-left="1in" fo:margin-right="1in"/></style:page-layout>'
              '</office:automatic-styles><office:master-styles><style:master-page style:name="Standard" '
              'style:page-layout-name="PL1"/></office:master-styles></office:document-styles>')
    return content, styles


def _style_maps(root, styles):
    """name -> {'b','i','u','s','align','parent'} from automatic and common styles."""
    out = {}
    for tree in (styles, root):
        if tree is None:
            continue
        for st in tree.iter(q("style:style")):
            name = st.get(q("style:name"))
            info = {"parent": st.get(q("style:parent-style-name"))}
            tp = st.find(q("style:text-properties"))
            if tp is not None:
                if tp.get(q("fo:font-weight")) in ("bold", "600", "700", "800", "900"):
                    info["b"] = True
                if tp.get(q("fo:font-style")) == "italic":
                    info["i"] = True
                if tp.get(q("style:text-underline-style")) not in (None, "none"):
                    info["u"] = True
                if tp.get(q("style:text-line-through-style")) not in (None, "none"):
                    info["s"] = True
            pp = st.find(q("style:paragraph-properties"))
            if pp is not None and pp.get(q("fo:text-align")):
                a = pp.get(q("fo:text-align"))
                info["align"] = {"left": "start", "right": "end", "start": "start", "end": "end",
                                 "center": "center", "justify": "justify"}.get(a, "start")
            out[name] = info
    return out


def _resolve(maps, name, key):
    seen = 0
    while name and seen < 10:
        info = maps.get(name, {})
        if key in info:
            return info[key]
        name, seen = info.get("parent"), seen + 1
    return None


def _runs(el, maps, inherited=None):
    inherited = inherited or {}
    runs = []

    def add(text, marks):
        if not text:
            return
        if runs and all(runs[-1].get(k, False) == marks.get(k, False) for k in "bius"):
            runs[-1]["text"] += text
        else:
            r = {"text": text}
            r.update({k: True for k in "bius" if marks.get(k)})
            runs.append(r)

    def walk(node, marks):
        add(node.text or "", marks)
        for child in node:
            tag = child.tag
            if tag == q("text:span"):
                st = child.get(q("text:style-name"))
                m = dict(marks)
                for k in "bius":
                    if _resolve(maps, st, k):
                        m[k] = True
                walk(child, m)
            elif tag == q("text:s"):
                add(" " * int(child.get(q("text:c"), "1")), marks)
            elif tag == q("text:tab"):
                add("\t", marks)
            elif tag == q("text:line-break"):
                add("\n", marks)
            elif tag in (q("text:a"), q("text:bookmark-ref"), q("text:reference-ref")):
                walk(child, marks)
            elif tag in (q("text:note"), q("office:annotation")):
                pass
            else:
                walk(child, marks)
            add(child.tail or "", marks)
    walk(el, inherited)
    return runs or [{"text": ""}]


def _read_odt(root, styles):
    maps = _style_maps(root, styles)
    blocks = []
    body = root.find(f"{q('office:body')}/{q('office:text')}")

    def para(el, kind):
        st = el.get(q("text:style-name"))
        base = {k: True for k in "bius" if _resolve(maps, st, k)}
        if kind == "p" and st:
            low = (st + " " + str(_resolve(maps, st, "parent") or "")).lower()
            if "title" in low and "sub" not in low:
                kind = "title"
            elif "quot" in low:
                kind = "quote"
        blocks.append({"kind": kind, "align": _resolve(maps, st, "align") or "start", "runs": _runs(el, maps, base)})

    def walk(container):
        for el in container:
            if el.tag == q("text:p"):
                para(el, "p")
            elif el.tag == q("text:h"):
                lvl = int(el.get(q("text:outline-level"), "1") or 1)
                para(el, "h%d" % min(3, max(1, lvl)))
            elif el.tag == q("text:list"):
                st = el.get(q("text:style-name")) or ""
                numbered = False
                for ls in root.iter(q("text:list-style")):
                    if ls.get(q("style:name")) == st and ls.find(q("text:list-level-style-number")) is not None:
                        numbered = True
                for item in el.iter(q("text:list-item")):
                    for p in item:
                        if p.tag in (q("text:p"), q("text:h")):
                            para(p, "number" if numbered else "bullet")
            elif el.tag in (q("text:section"), q("text:soft-page-break")):
                walk(el)
            elif el.tag == q("table:table"):
                for row in el.iter(q("table:table-row")):
                    cells = ["".join(c.itertext()) for c in row.iter(q("table:table-cell"))]
                    blocks.append({"kind": "p", "align": "start", "runs": [{"text": "\t".join(cells)}]})
    if body is not None:
        walk(body)
    return {"kind": "document", "version": MODEL_VERSION, "page": "letter", "blocks": blocks}


# ---------------------------------------------------------------- .ods
_REFTOK = re.compile(r"(\"(?:[^\"]|\"\")*\")|((?:'[^']+'|[A-Za-z_][\w]*)!)?(\$?[A-Za-z]{1,2}\$?\d+)(:\$?[A-Za-z]{1,2}\$?\d+)?(?![\w(])")


def _to_of(raw: str) -> str:
    """=SUM(A1:B2) -> of:=SUM([.A1:.B2]) (OpenFormula)."""
    def sub(m):
        if m.group(1):
            return m.group(1)
        sheet = m.group(2)
        a, b = m.group(3), m.group(4)
        sh = ""
        if sheet:
            name = sheet[:-1].strip("'")
            sh = "$'" + name.replace("'", "''") + "'"
        if b:
            return f"[{sh}.{a}:{sh}.{b[1:]}]" if sh else f"[.{a}:.{b[1:]}]"
        return f"[{sh}.{a}]"
    body = _REFTOK.sub(sub, raw[1:])
    out, in_str = [], False
    for ch in body:
        if ch == '"':
            in_str = not in_str
        out.append(";" if ch == "," and not in_str else ch)
    return "of:=" + "".join(out)


_OFREF = re.compile(r"\[\$?(?:'((?:[^']|'')+)'|([\w ]+))?\.(\$?[A-Z]{1,2}\$?\d+)(?::\$?(?:'(?:[^']|'')+'|[\w ]+)?\.(\$?[A-Z]{1,2}\$?\d+))?\]")


def _from_of(f: str) -> str:
    f = re.sub(r"^(of|oooc|msoxl):", "", f)
    if not f.startswith("="):
        f = "=" + f

    def sub(m):
        sheet = m.group(1) or m.group(2)
        a, b = m.group(3), m.group(4)
        pre = ""
        if sheet:
            name = sheet.replace("''", "'")
            pre = (f"'{name}'" if re.search(r"\W", name) else name) + "!"
        return pre + a + (":" + b if b else "")
    f = _OFREF.sub(sub, f)
    out, in_str = [], False
    for ch in f:
        if ch == '"':
            in_str = not in_str
        out.append("," if ch == ";" and not in_str else ch)
    return "".join(out)


def _cell_key(r, c):
    return f"{r},{c}"


def _ods(model):
    autos, used = [], {}
    tables = []
    for sh in model["sheets"]:
        cells = {tuple(map(int, k.split(","))): v for k, v in sh.get("cells", {}).items()}
        w = formula.Workbook()
        for s2 in model["sheets"]:
            w.add_sheet(s2["name"], {tuple(map(int, k.split(","))): v.get("v", "") for k, v in s2["cells"].items()})
        si = [s["name"] for s in model["sheets"]].index(sh["name"])
        nrows = max((k[0] for k in cells), default=-1) + 1
        ncols = max((k[1] for k in cells), default=-1) + 1
        cols = []
        for c in range(max(ncols, 1)):
            width = sh.get("widths", {}).get(str(c))
            if width:
                name = f"co{int(width)}"
                if name not in used:
                    used[name] = True
                    autos.append(f'<style:style style:name="{name}" style:family="table-column"><style:table-column-properties '
                                 f'style:column-width="{int(width) * 0.75:.0f}pt"/></style:style>')
                cols.append(f'<table:table-column table:style-name="{name}"/>')
            else:
                cols.append("<table:table-column/>")
        rows = []
        for r in range(nrows):
            out = []
            for c in range(ncols):
                cell = cells.get((r, c))
                if not cell:
                    out.append("<table:table-cell/>")
                    continue
                raw = cell.get("v", "")
                style = ""
                key = "".join(x for x in ("b" if cell.get("b") else "", "i" if cell.get("i") else "")) + \
                    (cell.get("align") or "")[:1] + (cell.get("fmt") or "")[:3]
                if key:
                    name = "ce_" + key
                    if name not in used:
                        used[name] = True
                        tp = []
                        if cell.get("b"):
                            tp.append('fo:font-weight="bold"')
                        if cell.get("i"):
                            tp.append('fo:font-style="italic"')
                        pp = ""
                        if cell.get("align") in ("start", "center", "end"):
                            pp = f'<style:paragraph-properties fo:text-align="{cell["align"]}"/>'
                        autos.append(f'<style:style style:name="{name}" style:family="table-cell" '
                                     f'style:parent-style-name="Default">{pp}'
                                     f'<style:text-properties {" ".join(tp)}/></style:style>')
                    style = f' table:style-name="{name}"'
                val = w.value(si, r, c)
                shown = escape(formula.display(val, cell.get("fmt", "general")))
                f = ""
                if raw.startswith("=") and len(raw) > 1:
                    f = f" table:formula={quoteattr(_to_of(raw))}"
                if isinstance(val, bool):
                    out.append(f'<table:table-cell{style}{f} office:value-type="boolean" office:boolean-value='
                               f'"{"true" if val else "false"}"><text:p>{shown}</text:p></table:table-cell>')
                elif isinstance(val, float):
                    vt = {"percent": "percentage", "currency": "currency"}.get(cell.get("fmt"), "float")
                    cur = ' office:currency="USD"' if vt == "currency" else ""
                    out.append(f'<table:table-cell{style}{f} office:value-type="{vt}"{cur} office:value="{val!r}">'
                               f'<text:p>{shown}</text:p></table:table-cell>')
                else:
                    text = raw if not f else shown
                    if isinstance(val, formula.Error):
                        text = val.code
                    out.append(f'<table:table-cell{style}{f} office:value-type="string"><text:p>{escape(str(text))}'
                               f'</text:p></table:table-cell>')
            rows.append("<table:table-row>" + "".join(out) + "</table:table-row>")
        if not rows:
            rows.append("<table:table-row><table:table-cell/></table:table-row>")
        tables.append(f'<table:table table:name={quoteattr(sh["name"])}>{"".join(cols)}{"".join(rows)}</table:table>')
    content = ('<?xml version="1.0" encoding="UTF-8"?>'
               f'<office:document-content {_XMLNS} office:version="1.3">'
               f'<office:automatic-styles>{"".join(autos)}</office:automatic-styles>'
               f'<office:body><office:spreadsheet>{"".join(tables)}</office:spreadsheet></office:body>'
               '</office:document-content>')
    styles = ('<?xml version="1.0" encoding="UTF-8"?>'
              f'<office:document-styles {_XMLNS} office:version="1.3"><office:styles>'
              '<style:style style:name="Default" style:family="table-cell"/></office:styles></office:document-styles>')
    return content, styles


def _read_ods(root, styles):
    maps = _style_maps(root, styles)
    sheets = []
    body = root.find(f"{q('office:body')}/{q('office:spreadsheet')}")
    for t in (body if body is not None else []):
        if t.tag != q("table:table"):
            continue
        cells = {}
        r = 0
        for row in t.iter(q("table:table-row")):
            rrep = min(int(row.get(q("table:number-rows-repeated"), "1")), 1000)
            c = 0
            row_cells = {}
            for cell in row:
                if cell.tag not in (q("table:table-cell"), q("table:covered-table-cell")):
                    continue
                crep = min(int(cell.get(q("table:number-columns-repeated"), "1")), 1000)
                f = cell.get(q("table:formula"))
                vt = cell.get(q("office:value-type"))
                if f:
                    raw = _from_of(f)
                elif vt in ("float", "percentage", "currency"):
                    raw = formula._fmt_number(float(cell.get(q("office:value"), "0")))
                elif vt == "boolean":
                    raw = "TRUE" if cell.get(q("office:boolean-value")) == "true" else "FALSE"
                elif vt == "date":
                    raw = (cell.get(q("office:date-value")) or "")[:10]
                else:
                    raw = "\n".join("".join(p.itertext()) for p in cell.iter(q("text:p")))
                if raw:
                    st = cell.get(q("table:style-name"))
                    info = {"v": raw}
                    if _resolve(maps, st, "b"):
                        info["b"] = True
                    if _resolve(maps, st, "i"):
                        info["i"] = True
                    al = _resolve(maps, st, "align")
                    if al in ("center", "end"):
                        info["align"] = al
                    if vt == "percentage":
                        info["fmt"] = "percent"
                    elif vt == "currency":
                        info["fmt"] = "currency"
                    elif vt == "date":
                        info["fmt"] = "date"
                    for k in range(crep):
                        row_cells[c + k] = dict(info)
                c += crep
            for k in range(rrep):
                for cc, info in row_cells.items():
                    cells[_cell_key(r + k, cc)] = dict(info)
            r += rrep
            if r > formula.MAX_ROWS:
                break
        sheets.append({"name": t.get(q("table:name")) or f"Sheet {len(sheets) + 1}", "cells": cells, "widths": {}})
    return {"kind": "spreadsheet", "version": MODEL_VERSION, "sheets": sheets}


# ---------------------------------------------------------------- .odp
THEME_ODP = {"paper": ("#FBF8F1", "#1F1D1A"), "ink": ("#17181C", "#F4F2EE"), "harbor": ("#123A5A", "#F2F7FB"),
             "meadow": ("#E7F1E4", "#1D3320"), "ember": ("#3A1610", "#FFF1E8")}


def _odp(model):
    bg, ink = THEME_ODP.get(model.get("theme", "paper"), THEME_ODP["paper"])
    pages = []
    for i, s in enumerate(model["slides"], 1):
        lay = s.get("layout", "content")
        frames = []
        title = escape(s.get("title", ""))
        lines = [x for x in s.get("body", "").split("\n")]
        if lay == "title":
            frames.append(f'<draw:frame presentation:class="title" draw:text-style-name="Ptitle" svg:x="1.5cm" svg:y="5.5cm" '
                          f'svg:width="25cm" svg:height="3.5cm"><draw:text-box><text:p>{title}</text:p></draw:text-box></draw:frame>')
            if s.get("body", "").strip():
                sub = "".join(f"<text:p>{escape(x)}</text:p>" for x in lines)
                frames.append('<draw:frame presentation:class="subtitle" draw:text-style-name="Pbody" svg:x="1.5cm" '
                              f'svg:y="9.5cm" svg:width="25cm" svg:height="3cm"><draw:text-box>{sub}</draw:text-box></draw:frame>')
        elif lay == "section":
            frames.append(f'<draw:frame presentation:class="title" draw:text-style-name="Ptitle" svg:x="1.5cm" svg:y="6.5cm" '
                          f'svg:width="25cm" svg:height="3cm"><draw:text-box><text:p>{title}</text:p></draw:text-box></draw:frame>')
        elif lay == "content":
            frames.append(f'<draw:frame presentation:class="title" draw:text-style-name="Ptitle" svg:x="1.5cm" svg:y="0.9cm" '
                          f'svg:width="25cm" svg:height="2.6cm"><draw:text-box><text:p>{title}</text:p></draw:text-box></draw:frame>')
            items = "".join(f"<text:list-item><text:p>{escape(x.lstrip('-• ').strip())}</text:p></text:list-item>"
                            for x in lines if x.strip())
            frames.append('<draw:frame presentation:class="outline" draw:text-style-name="Pbody" svg:x="1.5cm" svg:y="4cm" '
                          f'svg:width="25cm" svg:height="10.5cm"><draw:text-box><text:list>{items}</text:list>'
                          '</draw:text-box></draw:frame>')
        notes = ""
        if s.get("notes", "").strip():
            np = "".join(f"<text:p>{escape(x)}</text:p>" for x in s["notes"].split("\n"))
            notes = ('<presentation:notes><draw:frame presentation:class="notes" svg:x="2cm" svg:y="14cm" '
                     f'svg:width="17cm" svg:height="10cm"><draw:text-box>{np}</draw:text-box></draw:frame></presentation:notes>')
        pages.append(f'<draw:page draw:name="Slide {i}" draw:style-name="dp1" draw:master-page-name="Default">'
                     f'{"".join(frames)}{notes}</draw:page>')
    content = ('<?xml version="1.0" encoding="UTF-8"?>'
               f'<office:document-content {_XMLNS} office:version="1.3"><office:automatic-styles>'
               f'<style:style style:name="dp1" style:family="drawing-page"><style:drawing-page-properties '
               f'draw:fill="solid" draw:fill-color="{bg}" presentation:background-visible="true"/></style:style>'
               f'<style:style style:name="Ptitle" style:family="paragraph"><style:text-properties fo:color="{ink}" '
               'fo:font-size="40pt" fo:font-weight="bold"/></style:style>'
               f'<style:style style:name="Pbody" style:family="paragraph"><style:text-properties fo:color="{ink}" '
               'fo:font-size="24pt"/></style:style>'
               f'</office:automatic-styles><office:body><office:presentation>{"".join(pages)}</office:presentation>'
               '</office:body></office:document-content>')
    styles = ('<?xml version="1.0" encoding="UTF-8"?>'
              f'<office:document-styles {_XMLNS} office:version="1.3"><office:automatic-styles>'
              '<style:page-layout style:name="PM1"><style:page-layout-properties fo:page-width="28cm" '
              'fo:page-height="15.75cm" style:print-orientation="landscape"/></style:page-layout>'
              '</office:automatic-styles><office:master-styles><style:master-page style:name="Default" '
              'style:page-layout-name="PM1"/></office:master-styles></office:document-styles>')
    return content, styles


def _read_odp(root, styles):
    slides = []
    body = root.find(f"{q('office:body')}/{q('office:presentation')}")
    for page in (body if body is not None else []):
        if page.tag != q("draw:page"):
            continue
        title, body_lines, notes = "", [], []
        for frame in page:
            if frame.tag == q("presentation:notes"):
                for p in frame.iter(q("text:p")):
                    notes.append("".join(p.itertext()))
                continue
            if frame.tag != q("draw:frame"):
                continue
            cls = frame.get(q("presentation:class")) or ""
            paras = ["".join(p.itertext()) for p in frame.iter(q("text:p"))]
            if cls == "title" and not title:
                title = " ".join(x for x in paras if x)
            else:
                body_lines.extend(x for x in paras if x.strip())
        layout = "content" if body_lines else ("title" if not slides else "section")
        slides.append({"layout": layout, "title": title, "body": "\n".join(body_lines), "notes": "\n".join(notes)})
    return {"kind": "presentation", "version": MODEL_VERSION, "theme": "paper", "slides": slides}


# ---------------------------------------------------------------- CSV and text
def csv_to_model(text: str, delimiter: str = ",") -> dict:
    import csv
    cells = {}
    for r, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
        if r >= formula.MAX_ROWS:
            break
        for c, v in enumerate(row[:formula.MAX_COLS]):
            if v != "":
                cells[_cell_key(r, c)] = {"v": v}
    return {"kind": "spreadsheet", "version": MODEL_VERSION, "sheets": [{"name": "Sheet 1", "cells": cells, "widths": {}}]}


def model_to_csv(model: dict, sheet: int = 0) -> str:
    import csv
    sh = model["sheets"][sheet]
    w = formula.Workbook()
    for s in model["sheets"]:
        w.add_sheet(s["name"], {tuple(map(int, k.split(","))): v.get("v", "") for k, v in s["cells"].items()})
    rows, cols = w.extent(sheet)
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    for r in range(rows):
        wr.writerow([formula.display(w.value(sheet, r, c), sh["cells"].get(_cell_key(r, c), {}).get("fmt", "general"))
                     for c in range(cols)])
    return buf.getvalue()


_MD_INLINE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|~~[^~]+~~)")


def _md_runs(line: str):
    runs = []
    for part in _MD_INLINE.split(line):
        if not part:
            continue
        if part.startswith(("**", "__")) and len(part) > 4:
            runs.append({"text": part[2:-2], "b": True})
        elif part.startswith("~~") and len(part) > 4:
            runs.append({"text": part[2:-2], "s": True})
        elif part[0] in "*_" and part[-1] == part[0] and len(part) > 2:
            runs.append({"text": part[1:-1], "i": True})
        else:
            runs.append({"text": part})
    return runs or [{"text": ""}]


def text_to_model(text: str, markdown: bool = True) -> dict:
    blocks = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not markdown:
            blocks.append({"kind": "p", "align": "start", "runs": [{"text": line}]})
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            blocks.append({"kind": "h%d" % len(m.group(1)), "align": "start", "runs": _md_runs(m.group(2))})
        elif re.match(r"^\s*[-*+]\s+", line):
            blocks.append({"kind": "bullet", "align": "start", "runs": _md_runs(re.sub(r"^\s*[-*+]\s+", "", line))})
        elif re.match(r"^\s*\d+[.)]\s+", line):
            blocks.append({"kind": "number", "align": "start", "runs": _md_runs(re.sub(r"^\s*\d+[.)]\s+", "", line))})
        elif line.startswith(">"):
            blocks.append({"kind": "quote", "align": "start", "runs": _md_runs(line.lstrip("> "))})
        else:
            blocks.append({"kind": "p", "align": "start", "runs": _md_runs(line)})
    while len(blocks) > 1 and not "".join(r["text"] for r in blocks[-1]["runs"]).strip():
        blocks.pop()
    return {"kind": "document", "version": MODEL_VERSION, "page": "letter", "blocks": blocks or new_model("document")["blocks"]}


def model_to_markdown(model: dict) -> str:
    out, n = [], 0
    for b in model["blocks"]:
        text = ""
        for r in b["runs"]:
            t = r.get("text", "")
            if t.strip():
                if r.get("b"):
                    t = f"**{t}**"
                if r.get("i"):
                    t = f"*{t}*"
                if r.get("s"):
                    t = f"~~{t}~~"
            text += t
        k = b["kind"]
        n = n + 1 if k == "number" else 0
        out.append({"title": "# ", "h1": "## " if any(x["kind"] == "title" for x in model["blocks"]) else "# ",
                    "h2": "### ", "h3": "#### ", "bullet": "- ", "number": f"{n}. ", "quote": "> "}.get(k, "") + text)
    return "\n\n".join(out) + "\n"
