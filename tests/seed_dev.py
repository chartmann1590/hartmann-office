# Seed sample files (dev only), then open a given kind.
import os
from hoffice import odf
lib = win.library
if not lib.list():
    d = lib.create("document", "Quarterly plan", {"kind": "document", "version": 1, "page": "letter", "blocks": [
        {"kind": "title", "align": "start", "runs": [{"text": "Quarterly plan"}]},
        {"kind": "p", "align": "start", "runs": [{"text": "This quarter we focus on "}, {"text": "three things", "b": True}, {"text": " that move the studio forward. Each has an owner and a date."}]},
        {"kind": "h1", "align": "start", "runs": [{"text": "Goals"}]},
        {"kind": "bullet", "align": "start", "runs": [{"text": "Ship the office suite to Depot"}]},
        {"kind": "bullet", "align": "start", "runs": [{"text": "Grow the newsletter to 2,000 readers"}]},
        {"kind": "bullet", "align": "start", "runs": [{"text": "Launch two new ", }, {"text": "Android", "i": True}, {"text": " apps"}]},
        {"kind": "h2", "align": "start", "runs": [{"text": "Timeline"}]},
        {"kind": "number", "align": "start", "runs": [{"text": "December: polish and review"}]},
        {"kind": "number", "align": "start", "runs": [{"text": "January: release"}]},
        {"kind": "quote", "align": "start", "runs": [{"text": "Make it simple, then make it fast."}]}]})
    s = lib.create("spreadsheet", "Home budget", {"kind": "spreadsheet", "version": 1, "sheets": [{"name": "November", "widths": {"0": 160}, "cells": {
        "0,0": {"v": "Item", "b": True}, "0,1": {"v": "Planned", "b": True, "align": "end"}, "0,2": {"v": "Actual", "b": True, "align": "end"}, "0,3": {"v": "Difference", "b": True, "align": "end"},
        "1,0": {"v": "Rent"}, "1,1": {"v": "1650", "fmt": "currency"}, "1,2": {"v": "1650", "fmt": "currency"}, "1,3": {"v": "=B2-C2", "fmt": "currency"},
        "2,0": {"v": "Groceries"}, "2,1": {"v": "600", "fmt": "currency"}, "2,2": {"v": "548.20", "fmt": "currency"}, "2,3": {"v": "=B3-C3", "fmt": "currency"},
        "3,0": {"v": "Utilities"}, "3,1": {"v": "240", "fmt": "currency"}, "3,2": {"v": "263.75", "fmt": "currency"}, "3,3": {"v": "=B4-C4", "fmt": "currency"},
        "4,0": {"v": "Internet"}, "4,1": {"v": "80", "fmt": "currency"}, "4,2": {"v": "80", "fmt": "currency"}, "4,3": {"v": "=B5-C5", "fmt": "currency"},
        "5,0": {"v": "Fun"}, "5,1": {"v": "200", "fmt": "currency"}, "5,2": {"v": "312.40", "fmt": "currency"}, "5,3": {"v": "=B6-C6", "fmt": "currency"},
        "7,0": {"v": "Total", "b": True}, "7,1": {"v": "=SUM(B2:B6)", "fmt": "currency", "b": True}, "7,2": {"v": "=SUM(C2:C6)", "fmt": "currency", "b": True}, "7,3": {"v": "=B8-C8", "fmt": "currency", "b": True},
        "8,0": {"v": "Spent so far"}, "8,2": {"v": "=C8/B8", "fmt": "percent"}}}]})
    p = lib.create("presentation", "Studio update", {"kind": "presentation", "version": 1, "theme": "harbor", "slides": [
        {"layout": "title", "title": "Studio update", "body": "Hartmann Studios · November", "notes": "Welcome everyone."},
        {"layout": "content", "title": "What shipped", "body": "Hartmann Office for Luma\nTwo Android releases\n  Dead Tide 1.2\n  Nightsay 2.0\nA new blog every week", "notes": ""},
        {"layout": "section", "title": "Next quarter", "body": "", "notes": ""}]})
kind = os.environ.get("OPEN_KIND")
if kind:
    e = [x for x in lib.list() if x.kind == kind][0]
    win.open_entry(e)
win.refresh()
