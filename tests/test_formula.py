import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hoffice.formula import (Workbook, cell_name, col_index, col_name, display, parse_ref,  # noqa: E402
                             shift_formula)


def wb(cells, extra=None):
    w = Workbook()
    w.add_sheet("Sheet 1", {parse_ref(k): v for k, v in cells.items()})
    for name, c in (extra or {}).items():
        w.add_sheet(name, {parse_ref(k): v for k, v in c.items()})
    return w


def val(w, ref, sheet=0):
    return w.value(sheet, *parse_ref(ref))


def test_names():
    assert col_name(0) == "A" and col_name(25) == "Z" and col_name(26) == "AA" and col_name(701) == "ZZ"
    assert col_index("AA") == 26 and cell_name(0, 0) == "A1" and parse_ref("$B$3") == (2, 1)


def test_arithmetic_and_precedence():
    w = wb({"A1": "2", "A2": "3", "A3": "=A1+A2*4", "A4": "=(A1+A2)*4", "A5": "=2^3^2", "A6": "=-A1^2", "A7": "=50%"})
    assert val(w, "A3") == 14 and val(w, "A4") == 20 and val(w, "A5") == 512 and val(w, "A7") == 0.5
    assert val(w, "A6") == 4  # spreadsheet rule: negation binds tighter than ^


def test_functions():
    w = wb({"A1": "1", "A2": "2", "A3": "3", "A4": "hello", "B1": "=SUM(A1:A4)", "B2": "=AVERAGE(A1:A3)",
            "B3": "=IF(A1>0,\"yes\",\"no\")", "B4": "=COUNTIF(A1:A3,\">1\")", "B5": "=SUMIF(A1:A3,\">=2\")",
            "B6": "=CONCAT(A4,\" \",A3)", "B7": "=ROUND(2.345,2)", "B8": "=VLOOKUP(2,A1:A3,1,FALSE)",
            "B9": "=MAX(A1:A3)-MIN(A1:A3)", "B10": "=IFERROR(1/0,\"none\")", "B11": "=UPPER(LEFT(A4,2))"})
    assert val(w, "B1") == 6 and val(w, "B2") == 2 and val(w, "B3") == "yes" and val(w, "B4") == 2
    assert val(w, "B5") == 5 and val(w, "B6") == "hello 3" and abs(val(w, "B7") - 2.35) < 1e-9
    assert val(w, "B8") == 2 and val(w, "B9") == 2 and val(w, "B10") == "none" and val(w, "B11") == "HE"


def test_errors():
    w = wb({"A1": "=1/0", "A2": "=A3", "A3": "=A2", "A4": "=NOPE(1)", "A5": "=A1+1", "A6": "=\"a\"*2"})
    assert display(val(w, "A1")) == "#DIV/0!" and display(val(w, "A2")) == "#CYCLE!"
    assert display(val(w, "A4")) == "#NAME?" and display(val(w, "A5")) == "#DIV/0!" and display(val(w, "A6")) == "#VALUE!"


def test_cross_sheet():
    w = wb({"A1": "='Totals'!B2*2", "A2": "=SUM(Totals!B1:B2)"}, {"Totals": {"B1": "4", "B2": "5"}})
    assert val(w, "A1") == 10 and val(w, "A2") == 9


def test_shift():
    assert shift_formula("=A1+$B$2+C$3+\"A1\"", 1, 1) == "=B2+$B$2+D$3+\"A1\""
    assert shift_formula("=SUM(A1:A3)", 2, 0) == "=SUM(A3:A5)"
    assert shift_formula("=A1", -1, 0) == "=#REF!"


def test_display_formats():
    assert display(1234.5, "currency") == "$1,234.50" and display(0.25, "percent") == "25%"
    assert display(45000.0, "date") == "2023-03-15" and display(3.0) == "3"
