"""Drives the real editors inside the Luma runtime (needs a display; run with xvfb-run).

    flatpak run --command=python3 org.projectluma.Sdk//44 tests/test_ui.py
"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from hoffice import odf, render  # noqa: E402
from hoffice.library import Library  # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, None))
    except Exception:
        RESULTS.append((name, traceback.format_exc()))


def pump(n=50):
    ctx = GLib.MainContext.default()
    for _ in range(n):
        ctx.iteration(False)


# ---------------------------------------------------------------- documents
def t_writer():
    from hoffice.writer import Writer
    w = Writer(odf.new_model("document"))
    b = w.buffer

    def ret():  # what pressing Return does: our handler, else the text view's own newline
        if not w._key(None, 0xff0d, 0, 0):
            b.insert_at_cursor("\n")
    b.insert_at_cursor("My report")
    m = w.model()
    assert m["blocks"][0]["kind"] == "title" and m["blocks"][0]["runs"][0]["text"] == "My report", m
    # Return after a title starts a body paragraph
    b.place_cursor(b.get_end_iter())
    ret()
    b.insert_at_cursor("Plain text ")
    w.toggle_mark("b")
    b.insert_at_cursor("bold")
    m = w.model()
    assert m["blocks"][1]["kind"] == "p", m["blocks"]
    assert m["blocks"][1]["runs"] == [{"text": "Plain text "}, {"text": "bold", "b": True}], m["blocks"][1]
    # a bulleted list continues on Return and ends on an empty item
    ret()
    w.set_kind("bullet")
    b.insert_at_cursor("one")
    ret()
    b.insert_at_cursor("two")
    ret()
    ret()  # empty item: ends the list
    b.insert_at_cursor("after")
    kinds = [x["kind"] for x in w.model()["blocks"]]
    assert kinds == ["title", "p", "bullet", "bullet", "p"], kinds
    texts = ["".join(r["text"] for r in x["runs"]) for x in w.model()["blocks"]]
    assert texts == ["My report", "Plain text bold", "one", "two", "after"], texts
    # numbered list markers renumber
    w2 = Writer({"kind": "document", "version": 1, "page": "a4", "blocks": [
        {"kind": "number", "align": "start", "runs": [{"text": "a"}]},
        {"kind": "number", "align": "center", "runs": [{"text": "b"}]}]})
    s, e = w2.buffer.get_bounds()
    assert w2.buffer.get_text(s, e, True) == "1. a\n2. b\n", repr(w2.buffer.get_text(s, e, True))
    assert w2.model()["blocks"][1]["align"] == "center" and w2.model()["page"] == "a4"
    # find and replace
    n = w.replace_all("one", "first")
    assert n == 1 and "first" in odf.model_text(w.model())
    assert w.words() == 8, w.words()  # My report Plain text bold first two after


# ---------------------------------------------------------------- spreadsheets
def t_sheet():
    from hoffice.sheet import SheetView
    model = odf.new_model("spreadsheet")
    g = SheetView(model)
    g.set_raw(0, 0, "10")
    g.set_raw(1, 0, "20")
    g.set_raw(2, 0, "=SUM(A1:A2)")
    assert g.value(2, 0) == 30
    g.select(3, 0)
    assert g.autosum() == "=SUM(A1:A3)", g.autosum()
    # insert a row at the top: the formula follows its cells
    g.select(0, 0)
    g.insert_rows(False)
    assert g.raw(3, 0) == "=SUM(A2:A3)" and g.value(3, 0) == 30, (g.raw(3, 0), g.value(3, 0))
    assert g.undo() and g.raw(2, 0) == "=SUM(A1:A2)"
    # sort and fill down
    g2 = SheetView({"kind": "spreadsheet", "version": 1, "sheets": [{"name": "S", "widths": {}, "cells": {
        "0,0": {"v": "Name"}, "0,1": {"v": "Score"}, "1,0": {"v": "b"}, "1,1": {"v": "2"},
        "2,0": {"v": "c"}, "2,1": {"v": "3"}, "3,0": {"v": "a"}, "3,1": {"v": "1"}}}]})
    g2.select(1, 0)
    g2.sort(False)
    assert [g2.raw(r, 0) for r in range(4)] == ["Name", "a", "b", "c"], [g2.raw(r, 0) for r in range(4)]
    assert [g2.raw(r, 1) for r in range(1, 4)] == ["1", "2", "3"]
    g2.set_raw(1, 2, "=B2*2")
    g2.anchor, g2.cur = (1, 2), (3, 2)
    g2.fill_down()
    assert [g2.value(r, 2) for r in range(1, 4)] == [2.0, 4.0, 6.0]
    # copy and paste moves relative references
    g2.anchor = g2.cur = (1, 2)
    txt = g2.copy_text()
    g2.anchor = g2.cur = (1, 4)
    g2.paste_text(txt, (1, 2))
    assert g2.raw(1, 4) == "=D2*2", g2.raw(1, 4)
    # sheets
    i = g2.add_sheet()
    g2.set_sheet(i)
    g2.set_raw(0, 0, "=S!B4+1")
    assert g2.value(0, 0) == 4.0
    assert g2.rename_sheet("Totals") and g2.sheet_names() == ["S", "Totals"]
    # drawing works at several sizes
    win = Gtk.Window()
    win.set_child(g2)
    win.set_default_size(400, 300)
    win.present()
    pump(80)
    g2.queue_draw()
    pump(40)
    win.destroy()


# ---------------------------------------------------------------- presentations
def t_slides():
    from hoffice.slides import SlideEditor
    model = odf.new_model("presentation")
    s = SlideEditor(model)
    s.title_field.text = "Hello"
    assert model["slides"][0]["title"] == "Hello"
    s.add_slide("content")
    s.body_field.get_buffer().set_text("one\ntwo")
    assert model["slides"][1]["body"] == "one\ntwo" and s.index == 1
    s.move_slide(-1)
    assert model["slides"][0]["body"] == "one\ntwo" and s.index == 0
    s.duplicate_slide()
    assert len(model["slides"]) == 3
    assert s.delete_slide() and len(model["slides"]) == 2
    s.set_theme("ember")
    assert model["theme"] == "ember"
    assert s.undo() and model["theme"] == "paper"
    assert s.redo() and model["theme"] == "ember"


# ---------------------------------------------------------------- library, files, PDF
def t_library_and_pdf():
    root = tempfile.mkdtemp()
    lib = Library(root)
    docs = {k: lib.create(k) for k in odf.KINDS}
    for k, e in docs.items():
        m = lib.read(e)
        assert m["kind"] == k
        out = os.path.join(root, k + ".pdf")
        pages = render.write_pdf(out, m, e.title)
        assert pages >= 1 and open(out, "rb").read(5) == b"%PDF-", k
    e = docs["document"]
    lib.rename(e, "  Notes   for  me ")
    assert e.title == "Notes for me"
    lib.delete(e)
    assert e not in lib.list() and e in lib.list(deleted=True)
    lib.restore(e)
    assert lib.list(query="notes")[0].id == e.id
    copy = lib.duplicate(e)
    assert copy.title == "Notes for me copy" and len(lib.list()) == 4
    # an index lost after a crash rebuilds from the files on disk
    os.remove(lib.index_path)
    again = Library(root)
    assert len(again.list()) == 4
    # a long document flows onto several PDF pages
    long = {"kind": "document", "version": 1, "page": "letter",
            "blocks": [{"kind": "p", "align": "justify", "runs": [{"text": "word " * 120}]} for _ in range(40)]}
    assert render.write_pdf(os.path.join(root, "long.pdf"), long) > 3


def t_window():
    """The whole window opens each kind of file without errors."""
    from hoffice import app as A
    application = Adw.Application(application_id="com.charleshartmann.OfficeTest")
    done = {}

    def act(a):
        w = A.Window(a)
        for k in odf.KINDS:
            w.new_file(k)
            pump(30)
            assert w.kind == k and w.editor is not None
        w.ask_delete()
        w._delete()
        assert w.entry is None and len(w.library.list(deleted=True)) == 1
        done["ok"] = True
        a.quit()
    application.connect("activate", act)
    application.run([])
    assert done.get("ok")


for name, fn in (("documents", t_writer), ("spreadsheets", t_sheet), ("presentations", t_slides),
                 ("library and PDF", t_library_and_pdf), ("window", t_window)):
    check(name, fn)

bad = 0
for name, err in RESULTS:
    print(("ok   " if err is None else "FAIL ") + name)
    if err:
        bad += 1
        print(err)
print(f"{len(RESULTS) - bad} passed, {bad} failed")
sys.exit(1 if bad else 0)
