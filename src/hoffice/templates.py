# SPDX-License-Identifier: GPL-3.0-or-later
"""Office Pro templates: ready-made documents, spreadsheets and presentations to start from."""
from __future__ import annotations

import copy

from . import odf


def _p(text, kind="p", align="start", **marks):
    return {"kind": kind, "align": align, "runs": [{"text": text, **marks}]}


def _runs(kind, *runs, align="start"):
    return {"kind": kind, "align": align, "runs": [dict(r) if isinstance(r, dict) else {"text": r} for r in runs]}


def _doc(blocks, **extra):
    return {"kind": "document", "version": odf.MODEL_VERSION, "page": "letter", "blocks": blocks, **extra}


def _sheet(name, cells, widths=None):
    return {"kind": "spreadsheet", "version": odf.MODEL_VERSION,
            "sheets": [{"name": name, "cells": cells, "widths": widths or {}}]}


def _deck(theme, slides):
    return {"kind": "presentation", "version": odf.MODEL_VERSION, "theme": theme,
            "slides": [{"layout": l, "title": t, "body": b, "notes": n} for l, t, b, n in slides]}


def _c(v, **kw):
    return {"v": v, **kw}


RESUME = _doc([
    _p("Your Name", "title"),
    _p("City, State · you@example.com · (555) 123-4567 · yoursite.com", align="start"),
    _p("Summary", "h1"),
    _p("Two or three sentences on what you do best and the kind of work you're looking for."),
    _p("Experience", "h1"),
    _runs("h3", "Job title, Company"),
    _runs("p", {"text": "2023 – now", "i": True}),
    _p("What you were responsible for, with a number if you can", "bullet"),
    _p("Something you built, fixed or improved", "bullet"),
    _runs("h3", "Job title, Company"),
    _runs("p", {"text": "2019 – 2023", "i": True}),
    _p("A result you're proud of", "bullet"),
    _p("Education", "h1"),
    _runs("p", {"text": "Degree, School", "b": True}, " · 2019"),
    _p("Skills", "h1"),
    _p("Skill one · Skill two · Skill three · Skill four"),
])

COVER_LETTER = _doc([
    _p("Your Name"),
    _p("you@example.com · (555) 123-4567"),
    _p(""),
    _p("Date"),
    _p(""),
    _p("Hiring Manager"),
    _p("Company"),
    _p(""),
    _p("Dear Hiring Manager,"),
    _p("Open with the role you're applying for and one sentence on why it caught your eye."),
    _p("In the middle, connect two or three things you've done to what the job needs. Be specific: a project, a "
       "number, a problem you solved."),
    _p("Close by saying you'd welcome a conversation, and thank them for their time."),
    _p(""),
    _p("Sincerely,"),
    _p("Your Name"),
], footer="Your Name · you@example.com")

MEETING_NOTES = _doc([
    _p("Meeting notes", "title"),
    _runs("p", {"text": "Date: ", "b": True}, "    ", {"text": "Attendees: ", "b": True}),
    _p("Agenda", "h1"),
    _p("First topic", "number"),
    _p("Second topic", "number"),
    _p("Notes", "h1"),
    _p("What was said and decided.", "bullet"),
    _p("Decisions", "h1"),
    _p("Decision, and who made it", "bullet"),
    _p("Action items", "h1"),
    _p("Task · owner · due date", "bullet"),
    _p("Task · owner · due date", "bullet"),
], page_numbers=True)

INVOICE = _sheet("Invoice", {
    "0,0": _c("INVOICE", b=True), "0,3": _c("Invoice #", b=True, align="end"), "0,4": _c("1001", align="end"),
    "1,0": _c("Your Business"), "1,3": _c("Date", b=True, align="end"), "1,4": _c("=TODAY()", fmt="date", align="end"),
    "2,0": _c("you@example.com"), "2,3": _c("Due", b=True, align="end"), "2,4": _c("=E2+30", fmt="date", align="end"),
    "4,0": _c("Bill to", b=True), "5,0": _c("Client name"), "6,0": _c("Client address"),
    "8,0": _c("Description", b=True), "8,2": _c("Qty", b=True, align="end"), "8,3": _c("Rate", b=True, align="end"),
    "8,4": _c("Amount", b=True, align="end"),
    "9,0": _c("Design work"), "9,2": _c("10"), "9,3": _c("75", fmt="currency"), "9,4": _c("=C10*D10", fmt="currency"),
    "10,0": _c("Development"), "10,2": _c("20"), "10,3": _c("90", fmt="currency"), "10,4": _c("=C11*D11", fmt="currency"),
    "11,0": _c("Hosting (monthly)"), "11,2": _c("1"), "11,3": _c("25", fmt="currency"),
    "11,4": _c("=C12*D12", fmt="currency"),
    "13,3": _c("Subtotal", b=True, align="end"), "13,4": _c("=SUM(E10:E12)", fmt="currency"),
    "14,3": _c("Tax rate", align="end"), "14,4": _c("0.08", fmt="percent"),
    "15,3": _c("Tax", align="end"), "15,4": _c("=ROUND(E14*E15,2)", fmt="currency"),
    "16,3": _c("Total", b=True, align="end"), "16,4": _c("=E14+E16", fmt="currency", b=True),
    "18,0": _c("Thank you for your business."),
}, {"0": 200, "1": 40})

BUDGET = _sheet("Monthly budget", {
    "0,0": _c("Income", b=True), "0,1": _c("Planned", b=True, align="end"), "0,2": _c("Actual", b=True, align="end"),
    "1,0": _c("Pay"), "1,1": _c("4200", fmt="currency"), "1,2": _c("4200", fmt="currency"),
    "2,0": _c("Other"), "2,1": _c("300", fmt="currency"), "2,2": _c("180", fmt="currency"),
    "3,0": _c("Total income", b=True), "3,1": _c("=SUM(B2:B3)", fmt="currency", b=True),
    "3,2": _c("=SUM(C2:C3)", fmt="currency", b=True),
    "5,0": _c("Spending", b=True), "5,1": _c("Planned", b=True, align="end"), "5,2": _c("Actual", b=True, align="end"),
    "5,3": _c("Left", b=True, align="end"),
    "6,0": _c("Housing"), "6,1": _c("1500", fmt="currency"), "6,2": _c("1500", fmt="currency"), "6,3": _c("=B7-C7", fmt="currency"),
    "7,0": _c("Groceries"), "7,1": _c("600", fmt="currency"), "7,2": _c("540", fmt="currency"), "7,3": _c("=B8-C8", fmt="currency"),
    "8,0": _c("Transport"), "8,1": _c("300", fmt="currency"), "8,2": _c("280", fmt="currency"), "8,3": _c("=B9-C9", fmt="currency"),
    "9,0": _c("Utilities"), "9,1": _c("250", fmt="currency"), "9,2": _c("265", fmt="currency"), "9,3": _c("=B10-C10", fmt="currency"),
    "10,0": _c("Fun"), "10,1": _c("200", fmt="currency"), "10,2": _c("150", fmt="currency"), "10,3": _c("=B11-C11", fmt="currency"),
    "11,0": _c("Savings"), "11,1": _c("800", fmt="currency"), "11,2": _c("800", fmt="currency"), "11,3": _c("=B12-C12", fmt="currency"),
    "12,0": _c("Total spending", b=True), "12,1": _c("=SUM(B7:B12)", fmt="currency", b=True),
    "12,2": _c("=SUM(C7:C12)", fmt="currency", b=True), "12,3": _c("=SUM(D7:D12)", fmt="currency", b=True),
    "14,0": _c("Left over", b=True), "14,2": _c("=C4-C13", fmt="currency", b=True),
    "15,0": _c("Saved of income"), "15,2": _c("=C12/C4", fmt="percent"),
}, {"0": 170})

PROJECT_PLAN = _sheet("Project plan", {
    "0,0": _c("Task", b=True), "0,1": _c("Owner", b=True), "0,2": _c("Start", b=True, align="end"),
    "0,3": _c("Days", b=True, align="end"), "0,4": _c("Finish", b=True, align="end"), "0,5": _c("Status", b=True),
    "1,0": _c("Kick-off"), "1,1": _c("Alex"), "1,2": _c("=TODAY()", fmt="date"), "1,3": _c("1"),
    "1,4": _c("=C2+D2", fmt="date"), "1,5": _c("Done"),
    "2,0": _c("Research"), "2,1": _c("Sam"), "2,2": _c("=E2", fmt="date"), "2,3": _c("5"),
    "2,4": _c("=C3+D3", fmt="date"), "2,5": _c("In progress"),
    "3,0": _c("Design"), "3,1": _c("Jo"), "3,2": _c("=E3", fmt="date"), "3,3": _c("7"),
    "3,4": _c("=C4+D4", fmt="date"), "3,5": _c("Not started"),
    "4,0": _c("Build"), "4,1": _c("Alex"), "4,2": _c("=E4", fmt="date"), "4,3": _c("14"),
    "4,4": _c("=C5+D5", fmt="date"), "4,5": _c("Not started"),
    "5,0": _c("Launch"), "5,1": _c("Everyone"), "5,2": _c("=E5", fmt="date"), "5,3": _c("1"),
    "5,4": _c("=C6+D6", fmt="date"), "5,5": _c("Not started"),
    "7,0": _c("Total days", b=True), "7,3": _c("=SUM(D2:D6)", b=True),
    "8,0": _c("Tasks done", b=True), "8,3": _c('=COUNTIF(F2:F6,"Done")', b=True),
}, {"0": 150, "5": 110})

PITCH = _deck("midnight", [
    ("title", "Company name", "One line on what you do", "Introduce yourself and the company."),
    ("content", "The problem", "Who has it\nHow painful it is\nWhat they do today", ""),
    ("content", "Our solution", "What it is\nWhy it's better\nWhat it costs", ""),
    ("content", "Traction", "Customers or users\nGrowth so far\nWhat people say", ""),
    ("content", "Market", "How many people have the problem\nWhat they spend on it", ""),
    ("content", "The ask", "How much you're raising\nWhat it buys\nWhen you'll be back", "Thank them."),
    ("section", "Thank you", "", ""),
])

LESSON = _deck("sunrise", [
    ("title", "Lesson title", "Subject · Date", "Welcome the class."),
    ("content", "Today we'll learn", "First goal\nSecond goal\nThird goal", ""),
    ("section", "Part one", "", ""),
    ("content", "Key idea", "Explain it simply\nGive an example\n  A second example", "Check for questions."),
    ("content", "Try it", "A short activity\nWork in pairs\nShare one answer", "About 10 minutes."),
    ("content", "Recap", "What we covered\nHomework", ""),
])

TEMPLATES = (
    ("resume", "Résumé", "file-text", RESUME),
    ("cover-letter", "Cover letter", "file-text", COVER_LETTER),
    ("meeting-notes", "Meeting notes", "file-text", MEETING_NOTES),
    ("invoice", "Invoice", "table", INVOICE),
    ("budget", "Monthly budget", "table", BUDGET),
    ("project-plan", "Project plan", "table", PROJECT_PLAN),
    ("pitch", "Pitch deck", "monitor", PITCH),
    ("lesson", "Lesson", "monitor", LESSON),
)


def model(key: str) -> tuple[str, dict]:
    """(title, a fresh copy of the template's model)."""
    for k, title, _icon, m in TEMPLATES:
        if k == key:
            return title, copy.deepcopy(m)
    raise KeyError(key)
