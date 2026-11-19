import io
import os
import sys
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from hoffice import odf  # noqa: E402


def foreign(model):
    """Save, then drop our model copy so load() must read content.xml like any other file."""
    buf = io.BytesIO()
    odf.save(buf, model, "t")
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            if n != odf.MODEL_PATH:
                z.writestr(n, src.read(n))
    ext = odf.EXT[model["kind"]]
    return odf.load(out.getvalue(), "x" + ext), src


DOC = {"kind": "document", "version": 1, "page": "letter", "blocks": [
    {"kind": "title", "align": "center", "runs": [{"text": "Plan"}]},
    {"kind": "p", "align": "start", "runs": [{"text": "Hello "}, {"text": "bold", "b": True}, {"text": " and  "},
                                              {"text": "it", "i": True, "u": True}]},
    {"kind": "h2", "align": "start", "runs": [{"text": "Steps"}]},
    {"kind": "bullet", "align": "start", "runs": [{"text": "one"}]},
    {"kind": "bullet", "align": "start", "runs": [{"text": "two"}]},
    {"kind": "number", "align": "end", "runs": [{"text": "first"}]},
]}


def test_document_roundtrip_exact():
    buf = io.BytesIO()
    odf.save(buf, DOC, "Plan")
    assert odf.load(buf.getvalue(), "a.odt") == DOC


def test_document_valid_xml_and_foreign_read():
    m, z = foreign(DOC)
    for n in ("content.xml", "styles.xml", "meta.xml", "META-INF/manifest.xml"):
        ET.fromstring(z.read(n))
    assert z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    kinds = [b["kind"] for b in m["blocks"]]
    assert kinds == ["title", "p", "h2", "bullet", "bullet", "number"]
    assert m["blocks"][0]["align"] == "center" and m["blocks"][5]["align"] == "end"
    runs = m["blocks"][1]["runs"]
    assert runs[1] == {"text": "bold", "b": True} and runs[2]["text"] == " and  " and runs[3] == {"text": "it", "i": True, "u": True}


SHEET = {"kind": "spreadsheet", "version": 1, "sheets": [
    {"name": "Budget", "cells": {"0,0": {"v": "Item", "b": True}, "0,1": {"v": "Cost", "b": True, "align": "end"},
                                 "1,0": {"v": "Rent"}, "1,1": {"v": "1200", "fmt": "currency"},
                                 "2,0": {"v": "Food"}, "2,1": {"v": "450.5"},
                                 "3,0": {"v": "Total"}, "3,1": {"v": "=SUM(B2:B3)", "fmt": "currency"},
                                 "4,1": {"v": "=IF(B4>1000,\"high, really\",\"ok\")"}},
     "widths": {"0": 140}},
    {"name": "Notes 2", "cells": {"0,0": {"v": "=Budget!B4*2"}, "1,0": {"v": "='Notes 2'!A1+1"}}, "widths": {}}]}


def test_sheet_foreign_read_and_formulas():
    m, z = foreign(SHEET)
    root = ET.fromstring(z.read("content.xml"))
    fs = [c.get(odf.q("table:formula")) for c in root.iter(odf.q("table:table-cell")) if c.get(odf.q("table:formula"))]
    assert fs[:2] == ["of:=SUM([.B2:.B3])", 'of:=IF([.B4]>1000;"high, really";"ok")']
    assert fs[2] == "of:=[$'Budget'.B4]*2"
    c = m["sheets"][0]["cells"]
    assert c["3,1"]["v"] == "=SUM(B2:B3)" and c["1,1"]["v"] == "1200" and c["0,0"].get("b")
    assert c["4,1"]["v"] == '=IF(B4>1000,"high, really","ok")' and c["1,1"]["fmt"] == "currency"
    assert m["sheets"][1]["name"] == "Notes 2" and m["sheets"][1]["cells"]["0,0"]["v"] == "=Budget!B4*2"
    assert m["sheets"][1]["cells"]["1,0"]["v"] == "='Notes 2'!A1+1"


def test_csv():
    m = odf.csv_to_model('a,b\n1,"x, y"\n')
    assert m["sheets"][0]["cells"]["1,1"]["v"] == "x, y"
    assert odf.model_to_csv(SHEET).splitlines()[3] == "Total,\"$1,650.50\""


DECK = {"kind": "presentation", "version": 1, "theme": "harbor", "slides": [
    {"layout": "title", "title": "Q4 plan", "body": "Hartmann Studios", "notes": "Say hello"},
    {"layout": "content", "title": "Goals", "body": "Ship\nGrow", "notes": ""}]}


def test_presentation():
    buf = io.BytesIO()
    odf.save(buf, DECK)
    assert odf.load(buf.getvalue(), "d.odp") == DECK
    m, z = foreign(DECK)
    assert [s["title"] for s in m["slides"]] == ["Q4 plan", "Goals"]
    assert m["slides"][1]["body"] == "Ship\nGrow" and m["slides"][0]["notes"] == "Say hello"


def test_markdown():
    m = odf.text_to_model("# Title\n\nSome **bold** text\n- a\n1. b\n> q")
    assert [b["kind"] for b in m["blocks"]] == ["h1", "p", "p", "bullet", "number", "quote"]
    assert m["blocks"][2]["runs"][1] == {"text": "bold", "b": True}
    assert "**bold**" in odf.model_to_markdown(m)
