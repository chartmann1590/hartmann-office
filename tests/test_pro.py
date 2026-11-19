# SPDX-License-Identifier: GPL-3.0-or-later
"""Office Pro in the Luma runtime: version history, headers, footers and page numbers, premium themes."""
import io
import os
import sys
import tempfile
import time

import pytest

pytest.importorskip("gi")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from hoffice import odf, render  # noqa: E402
from hoffice.library import Library  # noqa: E402


def test_version_history():
    lib = Library(tempfile.mkdtemp())
    e = lib.create("document", "Draft")
    assert lib.versions(e) == []                        # nothing earlier than the first save
    m = lib.read(e)
    m["blocks"][0]["runs"][0]["text"] = "First words"
    lib.write(e, m)
    assert len(lib.versions(e)) == 1                    # the blank original is kept
    m["blocks"][0]["runs"][0]["text"] = "Second words"
    lib.write(e, m)
    assert len(lib.versions(e)) == 1                    # at most one copy every 10 minutes
    lib.snapshot(e, force=True)
    when, path = lib.versions(e)[0]
    assert time.time() - when < 60
    restored = lib.restore_version(e, lib.versions(e)[-1][1])
    assert restored["blocks"][0]["runs"][0]["text"] == ""
    assert lib.read(e)["blocks"][0]["runs"][0]["text"] == ""
    assert odf.model_text(odf.load(lib.versions(e)[0][1])).strip() == "Second words"   # restoring is undoable
    for _ in range(lib.KEEP_VERSIONS + 5):
        lib.snapshot(e, force=True)
        time.sleep(0.002)
    assert len(lib.versions(e)) == lib.KEEP_VERSIONS
    lib.remove(e)
    assert lib.versions(e) == []


def test_page_numbers_header_footer_pdf():
    blocks = [{"kind": "p", "align": "start", "runs": [{"text": "word " * 150}]} for _ in range(30)]
    model = {"kind": "document", "version": 1, "page": "letter", "blocks": blocks,
             "header": "Quarterly report", "footer": "Hartmann Studios", "page_numbers": True}
    lay = render.DocumentLayout(model)
    assert lay.header == "Quarterly report" and lay.page_numbers
    out = os.path.join(tempfile.mkdtemp(), "doc.pdf")
    pages = render.write_pdf(out, model)
    assert pages > 3 and open(out, "rb").read(5) == b"%PDF-"
    try:
        import subprocess
        text = subprocess.run(["pdftotext", out, "-"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        text = ""
    if text:
        assert f"Page 1 of {pages}" in text and f"Page {pages} of {pages}" in text
        assert text.count("Quarterly report") == pages and "Hartmann Studios" in text
    # the editor keeps page set-up it doesn't show
    buf = io.BytesIO()
    odf.save(buf, model, "r")
    back = odf.load(buf.getvalue(), "r.odt")
    assert back["header"] == "Quarterly report" and back["page_numbers"] is True


def test_premium_themes():
    for t in render.PRO_THEMES:
        assert t in render.THEMES and t in odf.THEMES
    m = odf.new_model("presentation")
    m["theme"] = "midnight"
    buf = io.BytesIO()
    odf.save(buf, m, "d")
    assert odf.load(buf.getvalue(), "d.odp")["theme"] == "midnight"
