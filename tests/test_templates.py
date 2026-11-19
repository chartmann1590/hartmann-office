# SPDX-License-Identifier: GPL-3.0-or-later
"""Office Pro templates: every one loads, saves and calculates without an error (no GTK needed)."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from hoffice import odf, templates  # noqa: E402
from hoffice.formula import Workbook  # noqa: E402

PRO_THEMES = {"midnight", "sunrise", "forest", "slate"}


def test_templates_load_and_calculate():
    assert len(templates.TEMPLATES) == 8
    for key, title, _icon, _m in templates.TEMPLATES:
        name, model = templates.model(key)
        assert name == title
        buf = io.BytesIO()
        odf.save(buf, model, name)                       # every template survives a save and a load
        back = odf.load(buf.getvalue(), "t." + odf.EXT[model["kind"]])
        assert back["kind"] == model["kind"]
        if model["kind"] == "spreadsheet":
            for s in back["sheets"]:
                w = Workbook()
                w.add_sheet(s["name"], {tuple(int(x) for x in k.split(",")): v["v"] for k, v in s["cells"].items()})
                for k in s["cells"]:
                    r, c = (int(x) for x in k.split(","))
                    v = w.value(0, r, c)
                    assert not (isinstance(v, str) and v.startswith("#")), (key, k, s["cells"][k]["v"], v)
        if model["kind"] == "presentation":
            assert back["theme"] in PRO_THEMES     # Pro templates show off Pro themes
    # copies are independent
    _t, a = templates.model("resume")
    a["blocks"][0]["runs"][0]["text"] = "changed"
    assert templates.model("resume")[1]["blocks"][0]["runs"][0]["text"] == "Your Name"
    assert templates.model("invoice")[1]["sheets"][0]["cells"]["16,4"]["v"] == "=E14+E16"


def test_invoice_totals():
    _t, m = templates.model("invoice")
    s = m["sheets"][0]
    w = Workbook()
    w.add_sheet("I", {tuple(int(x) for x in k.split(",")): v["v"] for k, v in s["cells"].items()})
    assert w.value(0, 13, 4) == 750 + 1800 + 25          # subtotal
    assert abs(w.value(0, 16, 4) - (2575 + round(2575 * 0.08, 2))) < 0.001


