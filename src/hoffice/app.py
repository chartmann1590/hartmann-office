# SPDX-License-Identifier: GPL-3.0-or-later
"""Hartmann Office: documents, spreadsheets and presentations in one Luma app.

Shape: places and content (Tasks, Notes). The sidebar holds the places
(All files, Documents, Spreadsheets, Presentations, Deleted) and the files in
the chosen place; the island holds the open file's editor; the action bar
holds what you do to it right now. The title row carries the document header
with Export (or Present) as its one key.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from luma_appkit import (  # noqa: E402
    ActionCenter, AppWindow, BarAction, BarEntry, BarMenu, Command, CommandGroup, CommandRegistry,
    DestructiveDialog, DocumentHeader, EmptyState, FileRequest, Island, NavigationSidebar, RowLead,
    SidebarFoot, SidebarRow, SidebarToggle, StackedButton, StackedButtons, TitleIsland, Toast, ToastHost,
    ask_for_file,
)
from luma_appkit.action_bubble import MenuItem  # noqa: E402

from . import odf, render, templates  # noqa: E402
from .hsbilling import Billing  # noqa: E402
from .hsupdates import Updates  # noqa: E402
from .updates_ui import Updater  # noqa: E402
from .paywall import Paywall  # noqa: E402
from .library import KIND_ICONS, KIND_NAMES, Library  # noqa: E402

APP_ID = "com.charleshartmann.Office"
APP_NAME = "Hartmann Office"
VERSION = "1.2.0"
PLACES = (("all", "All files", "folder"), ("document", "Documents", "file-text"),
          ("spreadsheet", "Spreadsheets", "table"), ("presentation", "Presentations", "monitor"),
          ("deleted", "Deleted", "trash-2"))
SAVE_DELAY_MS = 700
PRO = "Office Pro"
PRO_PRODUCTS = ("office_lifetime", "office_pro:yearly", "office_pro:monthly")  # best first
PRO_FEATURES = (
    ("layout-template", "Templates", "Résumé, cover letter, meeting notes, invoice, budget, project plan, pitch deck and lesson."),
    ("palette", "Premium slide themes", "Midnight, Sunrise, Forest and Slate."),
    ("history", "Version history", "Go back to an earlier version of any file, and undo that too."),
    ("file-text", "Headers, footers and page numbers", "On every page of a printed or exported document."),
)


def when(t: float) -> str:
    d = time.time() - t
    if d < 60:
        return "Just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    lt, now = time.localtime(t), time.localtime()
    if lt.tm_yday == now.tm_yday and lt.tm_year == now.tm_year:
        return time.strftime("%-I:%M %p", lt)
    if d < 6 * 86400:
        return time.strftime("%A", lt)
    return time.strftime("%b %-d" if lt.tm_year == now.tm_year else "%b %-d, %Y", lt)


class Window(AppWindow):
    def __init__(self, app):
        self.library = Library()
        self.billing = Billing("hartmann-office", PRO_PRODUCTS, os.path.join(self.library.root, "license.json"))
        self.place = "all"
        self.query = ""
        self.entry = None        # the open library Entry
        self.editor = None       # Writer, SheetView or SlideEditor
        self.kind = None
        self._save_id = 0
        self._saved = True
        self._rows: dict = {}
        self._place_rows: dict = {}
        self._populating = False
        self._clipboard_origin = None

        commands = CommandRegistry([
            CommandGroup("New", (
                Command("file.new-document", "New document", lambda: self.new_file("document"), icon="file-text",
                        shortcut=("Ctrl", "N")),
                Command("file.new-spreadsheet", "New spreadsheet", lambda: self.new_file("spreadsheet"), icon="table",
                        shortcut=("Ctrl", "Shift", "N")),
                Command("file.new-presentation", "New presentation", lambda: self.new_file("presentation"),
                        icon="monitor", shortcut=("Ctrl", "Alt", "N")),
            )),
            CommandGroup("File", (
                Command("file.open", "Open…", self.open_file, icon="folder-open", shortcut=("Ctrl", "O")),
                Command("file.save-copy", "Save a copy…", self.save_copy, icon="download", shortcut=("Ctrl", "Shift", "S"),
                        enabled=lambda: self.entry is not None),
                Command("file.export-pdf", "Export as PDF…", self.export_pdf, icon="share", shortcut=("Ctrl", "E"),
                        enabled=lambda: self.entry is not None),
                Command("file.print", "Print…", self.print_file, icon="printer", shortcut=("Ctrl", "P"),
                        enabled=lambda: self.entry is not None),
                Command("file.present", "Present", self.present_slides, icon="play", shortcut=("F5",),
                        enabled=lambda: self.kind == "presentation"),
                Command("file.rename", "Rename…", self.ask_rename, icon="edit-rename",
                        enabled=lambda: self.entry is not None and not self.entry.deleted),
                Command("file.duplicate", "Duplicate", self.duplicate, icon="copy",
                        enabled=lambda: self.entry is not None and not self.entry.deleted),
                Command("file.delete", "Move to Deleted", self.ask_delete, icon="trash-2", destructive=True,
                        enabled=lambda: self.entry is not None and not self.entry.deleted),
            )),
            CommandGroup("App", (
                Command("app.updates", "Check for updates…", lambda: self.updater.open(), icon="refresh-cw"),
            )),
            CommandGroup(PRO, (
                Command("pro.open", f"{PRO}…", lambda: self.open_pro(), icon="sparkles"),
                Command("pro.template", "New from a template…", lambda: self.ask_template(), icon="layout-template"),
                Command("pro.versions", "Version history…", lambda: self.ask_versions(), icon="history",
                        enabled=lambda: self.entry is not None and not self.entry.deleted),
                Command("pro.page", "Header, footer and page numbers…", lambda: self.ask_page_setup(),
                        icon="file-text", enabled=lambda: self.kind == "document"),
            )),
            CommandGroup("Edit", (
                Command("edit.undo", "Undo", self.undo, icon="undo-2", shortcut=("Ctrl", "Z"),
                        enabled=lambda: self.editor is not None),
                Command("edit.redo", "Redo", self.redo, icon="redo", shortcut=("Ctrl", "Shift", "Z"),
                        enabled=lambda: self.editor is not None),
                Command("edit.find", "Find and replace…", self.find, icon="search", shortcut=("Ctrl", "F"),
                        enabled=lambda: self.kind == "document"),
            )),
        ])
        super().__init__(application=app, app_id=APP_ID, title=APP_NAME, icon_name=APP_ID, commands=commands,
                         default_width=1180, default_height=780, minimum_width=360, minimum_height=294)
        self.commands_registry = commands
        self._css()

        # Sidebar: the places, then the files in the chosen place.
        self.sidebar = NavigationSidebar(variant="files")
        self.sidebar.append_footer(SidebarFoot(search="Search files", on_search=self.search,
                                               add=("New", "square-pen", self.ask_new)))
        self.sidebar.list.connect("row-activated", self._row_activated)

        # The island: an editor, or an empty state.
        self.island = Island()
        self.stack = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        from luma_appkit.lumaui import reduced_motion
        self.stack.set_transition_duration(0 if reduced_motion() else 160)  # no fade when motion is reduced
        self.empty = EmptyState("Nothing open", "Make something new, or open a file from another app.",
                                "lumaui-square-pen-symbolic", primary=("New document", lambda: self.new_file("document")),
                                secondary=("Open…", self.open_file))
        self.stack.add_named(self.empty, "empty")
        self.island.append(self.stack)
        self.host = ToastHost(self.island)
        body = Gtk.Box()
        body.append(self.sidebar)
        main = Gtk.Box(hexpand=True)
        main.append(self.host)
        body.append(main)
        # On a phone: ☰ and the open file's name are one island at the top left; tapping ☰ grows it
        # into the sidebar (Ari's shape). On a computer the toggle sits in the title row (F9).
        self.title_island = TitleIsland(APP_NAME, "", lead="menu")
        self.island_key = self.title_island.add_trailing(TitleIsland.button("share", "Export as PDF", self._island_key))
        self.title_island.add_trailing(TitleIsland.button("ellipsis", "More", self._island_more))
        self.sidebar_toggle = SidebarToggle(self.sidebar, island=self.title_island)  # after the sidebar is laid out
        self.set_leading(self.sidebar_toggle)
        self.set_body(body)
        self.title_island.float_over(body)
        self.tier_watch.connect("tier-changed", lambda *_: self._tiered())
        self._tiered()
        self.center = ActionCenter().attach(self.host)

        self.header = DocumentHeader(APP_NAME, icon=APP_ID, subtitle="", more=commands)
        self.header.set_visible(False)
        self.set_title_content(self.header)

        self.connect("close-request", self._closing)
        self.paywall = Paywall(self, self.billing, PRO, PRO_FEATURES, open_uri=self.open_uri,
                               toast=lambda t, k="done": Toast.show(self.host, t, kind=k), changed=self._pro_changed)
        if self.billing.needs_revalidation():
            import threading
            threading.Thread(target=self.billing.revalidate, daemon=True).start()
        self.updates = Updates(APP_ID, "chartmann1590/hartmann-office", VERSION,
                               os.path.join(self.library.root, "updates.json"),
                               os.path.join(GLib.get_user_cache_dir(), "hartmann-office", "updates"))
        self.updater = Updater(self, self.updates, APP_NAME, grow=lambda k, w: self.center.grow(k, w, wide=True),
                               fold=lambda: self.center.fold(),
                               toast=lambda t, k="done", action=None: Toast.show(self.host, t, kind=k,
                                                                               **({"action": action} if action else {})))
        GLib.timeout_add_seconds(8, self.updater.start)
        self.refresh()
        recent = self.library.list()
        if recent:
            self.open_entry(recent[0])
        else:
            self.show_bar()

    def _tiered(self):
        # Content starts under the floating title island on a phone.
        self.stack.set_margin_top(64 if self.tier == "phone" else 0)

    def _island_key(self):
        if self.kind == "presentation":
            self.present_slides()
        elif self.entry is not None:
            self.export_pdf()
        else:
            self.open_file()

    def _island_more(self):
        from luma_appkit import MenuDrawer
        MenuDrawer.present(self, self.commands_registry)

    # ------------------------------------------------------------ styling (our content only)
    def _css(self):
        from luma_appkit import add_style_sheet
        path = os.path.join(os.path.dirname(__file__), "hoffice.css")
        if os.path.exists(path):
            add_style_sheet(path)

    # ------------------------------------------------------------ sidebar
    def refresh(self):
        self._populating = True
        self.sidebar.clear()
        self._rows, self._place_rows = {}, {}
        counts = {"all": len(self.library.list()), "deleted": len(self.library.list(deleted=True))}
        for k in odf.KINDS:
            counts[k] = len(self.library.list(k))
        for key, title, icon in PLACES:
            if key == "deleted" and not counts["deleted"]:
                continue
            row = SidebarRow(title, lead=RowLead.icon(icon), trail=counts.get(key) or None)
            row.place = key
            self._place_rows[key] = row
            self.sidebar.append_row(row)
        name = dict((k, t) for k, t, _ in PLACES)[self.place]
        entries = self.library.list(None if self.place in ("all", "deleted") else self.place,
                                    deleted=self.place == "deleted", query=self.query)
        self.sidebar.append_section(("Results" if self.query else name))
        for e in entries:
            meta = when(e.deleted if e.deleted else e.modified)
            row = SidebarRow(e.title, lead=RowLead.icon(KIND_ICONS[e.kind]), meta=meta, subtitle=KIND_NAMES[e.kind])
            row.entry = e
            self._rows[e.id] = row
            self.sidebar.append_row(row)
        if not entries:
            from luma_appkit import ListEmptyState
            self.sidebar.list.append(ListEmptyState("No matches" if self.query else
                                                    ("Nothing in Deleted" if self.place == "deleted" else "No files yet")))
        self._select_rows()
        self._populating = False

    def _select_rows(self):
        lst = self.sidebar.list
        target = self._rows.get(self.entry.id) if self.entry else None
        if target is not None:
            lst.select_row(target)
        else:
            lst.unselect_all()
        for key, row in self._place_rows.items():
            row.set_state_flags(Gtk.StateFlags.CHECKED, False) if key == self.place else row.unset_state_flags(Gtk.StateFlags.CHECKED)

    def _row_activated(self, _list, row):
        if self._populating:
            return
        if getattr(row, "place", None):
            self.place = row.place
            self.refresh()
            return
        e = getattr(row, "entry", None)
        if e is not None and (self.entry is None or e.id != self.entry.id):
            self.open_entry(e)

    def search(self, text: str):
        self.query = text
        self.refresh()

    # ------------------------------------------------------------ files
    def ask_new(self):
        trio = StackedButtons([StackedButton("file-text", "Document", on_click=lambda: self._new_from_panel("document")),
                               StackedButton("table", "Spreadsheet", on_click=lambda: self._new_from_panel("spreadsheet")),
                               StackedButton("monitor", "Presentation",
                                             on_click=lambda: self._new_from_panel("presentation")),
                               StackedButton("layout-template", "Template", on_click=self.ask_template)])
        self.center.grow("new", trio)

    def _new_from_panel(self, kind):
        self.center.fold()
        self.new_file(kind)

    def new_file(self, kind: str):
        self.flush()
        e = self.library.create(kind)
        if self.place not in ("all", kind):
            self.place = kind
        self.query = ""
        self.open_entry(e)
        self.refresh()
        Toast.show(self.host, f"New {KIND_NAMES[kind].lower()} created", kind="added")

    def open_entry(self, e):
        self.flush()
        try:
            model = self.library.read(e)
        except Exception as ex:  # a damaged file must not take the app down
            Toast.show(self.host, f"Couldn't open “{e.title}”: {ex}", kind="error")
            return
        try:
            editor = self._make_editor(e.kind, model)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            Toast.show(self.host, f"Couldn't open “{e.title}”: {ex}", kind="error")
            return
        if self.editor is not None:
            self.stack.remove(self.editor)
        self.entry, self.kind, self.editor = e, e.kind, editor
        self.stack.add_named(self.editor, "editor")
        self.stack.set_visible_child(self.editor)
        self.header.set_visible(True)
        self._header_for(e)
        self._saved = True
        self._update_subtitle()
        self.show_bar()
        self._select_rows()
        GLib.idle_add(self._focus_editor)

    def _make_editor(self, kind, model):
        if kind == "document":
            from .writer import Writer
            ed = Writer(model)
            ed.connect("changed", self._edited)
        elif kind == "spreadsheet":
            ed = self._sheet_page(model)
        else:
            from .slides import SlideEditor
            ed = SlideEditor(model)
            ed.connect("changed", self._edited)
            ed.connect("moved", lambda *_: self.show_bar())
            ed.pro = lambda: self.pro
            ed.locked = self.need_pro
        return ed

    def _focus_editor(self):
        w = self.editor
        if w is None:
            return False
        target = getattr(w, "view", None) or getattr(w, "grid", None) or w
        target.grab_focus()
        return False

    def _header_for(self, e):
        # DocumentHeader takes its key at construction, so a new header is made per kind.
        primary = "Present" if e.kind == "presentation" else "Export"
        on_primary = self.present_slides if e.kind == "presentation" else self.export_pdf
        self.header = DocumentHeader(e.title, icon=APP_ID, subtitle=KIND_NAMES[e.kind], share=self._share,
                                     primary=primary, on_primary=on_primary, more=self.commands_registry)
        self.set_title_content(self.header)
        icon, label = ("play", "Present") if e.kind == "presentation" else ("share", "Export as PDF")
        from luma_appkit import icons
        self.island_key.set_child(icons.image(icon))
        self.island_key.set_tooltip_text(label)
        self.island_key.update_property([Gtk.AccessibleProperty.LABEL], [label])

    def _update_subtitle(self):
        if not self.entry:
            return
        parts = [KIND_NAMES[self.kind]]
        if self.kind == "document" and self.editor is not None:
            n = self.editor.words()
            parts.append(f"{n:,} word" + ("" if n == 1 else "s"))
        if self.entry.deleted:
            parts.append("In Deleted")
        else:
            parts.append("Saved" if self._saved else "Edited")
        self.header.set_title(self.entry.title, " · ".join(parts))
        self.title_island.set_title(self.entry.title, " · ".join(parts))

    def close_file(self):
        self.flush()
        if self.editor is not None:
            self.stack.remove(self.editor)
        self.editor = self.entry = self.kind = None
        self.stack.set_visible_child_name("empty")
        self.header.set_visible(False)
        self.title_island.set_title(APP_NAME, "")
        self.show_bar()
        self._select_rows()

    # ------------------------------------------------------------ Office Pro
    @property
    def pro(self) -> bool:
        return self.billing.owns()

    def open_uri(self, url: str):
        Gtk.UriLauncher.new(url).launch(self, None, None, None)

    def open_pro(self):
        self.center.grow("pro", self.paywall.panel, wide=True)

    def need_pro(self, what: str) -> bool:
        if self.pro:
            return True
        Toast.show(self.host, f"{what} come with {PRO}" if what.endswith("s") else f"{what} comes with {PRO}",
                   kind="done")
        self.open_pro()
        return False

    def _pro_changed(self):
        # the upgrade panel stays open to say thank you; the bar catches up when it folds
        if self.center.grown != "pro":
            self.show_bar()

    def ask_template(self):
        from luma_appkit import PanelHeading, PanelRow
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(PanelHeading("Start from a template" + ("" if self.pro else f" · {PRO}")))
        for key, title, icon, model in templates.TEMPLATES:
            kind = KIND_NAMES[model["kind"]]
            box.append(PanelRow(title, icon=icon, subtitle=kind, on_activate=lambda k=key: self._from_template(k)))
        self.center.grow("template", box)

    def _from_template(self, key: str):
        if not self.need_pro("Templates"):
            return
        self.flush()
        title, model = templates.model(key)
        e = self.library.create(model["kind"], title, model)
        self.place, self.query = "all", ""
        self.open_entry(e)
        self.refresh()
        Toast.show(self.host, f"New {title.lower()} from the template", kind="added")

    def ask_versions(self):
        if self.entry is None or self.entry.deleted:
            return
        from luma_appkit import PanelHeading, PanelRow
        self.flush()
        vs = self.library.versions(self.entry)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(PanelHeading("Version history" + ("" if self.pro else f" · {PRO}")))
        if not vs:
            box.append(PanelRow("No earlier versions yet", icon="history", sensitive=False,
                                subtitle="A version is kept every 10 minutes while you work."))
        for t, path in vs[:20]:
            try:
                size = f"{os.path.getsize(path) // 1024 + 1} KB"
            except OSError:
                size = ""
            box.append(PanelRow(when(t), icon="history", subtitle=time.strftime("%B %-d, %Y at %-I:%M %p", time.localtime(t)),
                                detail=size, on_activate=lambda p=path, t=t: self._restore_version(p, t)))
        self.center.grow("versions", box)

    def _restore_version(self, path: str, t: float):
        if not self.need_pro("Version history"):
            return
        e = self.entry
        try:
            self.library.restore_version(e, path)
        except Exception as ex:
            Toast.show(self.host, f"Couldn't restore that version: {ex}", kind="error")
            return
        self.open_entry(e)
        self.refresh()

        def undo():
            newest = self.library.versions(e)
            if newest:
                self.library.restore_version(e, newest[0][1])
                self.open_entry(e)
        Toast.show(self.host, f"Restored the version from {when(t).lower()}", kind="done", undo=undo)

    def ask_page_setup(self):
        if self.kind != "document" or self.editor is None:
            return
        if not self.need_pro("Headers, footers and page numbers"):
            return
        from luma_appkit import PanelHeading, PanelRow, TextButton, TextField
        w = self.editor
        setup = dict(getattr(w, "page_setup", {}))
        header = TextField("Header", value=setup.get("header", ""), placeholder="At the top of every page", size="panel")
        footer = TextField("Footer", value=setup.get("footer", ""), placeholder="At the bottom of every page", size="panel")
        numbers = {"on": bool(setup.get("page_numbers"))}

        def done():
            new = {"header": header.text.strip(), "footer": footer.text.strip(), "page_numbers": numbers["on"]}
            w.page_setup = {k: v for k, v in new.items() if v}
            self.center.fold()
            self._edited()
            Toast.show(self.host, "Page set-up saved. You'll see it when you export or print.", kind="saved")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(PanelHeading("Header, footer and page numbers"))
        box.append(header)
        box.append(footer)
        box.append(PanelRow("Page numbers", icon="list-ordered", toggle=numbers["on"],
                            on_toggle=lambda on: numbers.update(on=on)))
        box.append(TextButton("Done", icon="check", style="fill", on_click=done))
        self.center.grow("page-setup", box)

    # ------------------------------------------------------------ saving
    def _edited(self, *_):
        if self.entry is None or self.entry.deleted:
            return
        self._saved = False
        self._update_subtitle()
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(SAVE_DELAY_MS, self._save_now)

    def current_model(self) -> dict | None:
        if self.editor is None:
            return None
        if self.kind == "document":
            return self.editor.model()
        if self.kind == "spreadsheet":
            return self.grid.model
        return self.editor.model

    def _save_now(self):
        self._save_id = 0
        if self.entry is None or self.entry.deleted:
            return False
        try:
            self.library.write(self.entry, self.current_model())
            self._saved = True
        except OSError as ex:
            Toast.show(self.host, f"Couldn't save: {ex.strerror or ex}", kind="error")
        self._update_subtitle()
        row = self._rows.get(self.entry.id)
        if row is not None and hasattr(row, "set_meta"):
            row.set_meta(when(self.entry.modified))
        return False

    def flush(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_now()

    def _closing(self, *_):
        self.flush()
        return False

    # ------------------------------------------------------------ rename, duplicate, delete
    def ask_rename(self):
        if self.entry is None:
            return
        from luma_appkit import ActionEditor, TextField
        field = TextField("Name", value=self.entry.title, on_activate=lambda t: self._rename(t))
        self.center.set_editor(ActionEditor(f"Rename {KIND_NAMES[self.kind].lower()}", "edit-rename",
                                            body=field, primary=BarAction("check", "Rename",
                                                                          on_activate=lambda: self._rename(field.text)),
                                            submit_on_return=True))
        self.center.grow()
        GLib.idle_add(lambda: field.grab_focus() and False)

    def _rename(self, title):
        self.center.fold()
        if self.entry and title.strip() and title.strip() != self.entry.title:
            self.library.rename(self.entry, title)
            self._update_subtitle()
            self.refresh()
            Toast.show(self.host, "Renamed", kind="done")

    def duplicate(self):
        if self.entry is None:
            return
        self.flush()
        e = self.library.duplicate(self.entry)
        self.open_entry(e)
        self.refresh()
        Toast.show(self.host, "Duplicated", kind="added")

    def ask_delete(self):
        if self.entry is None:
            return
        DestructiveDialog.in_bar(self.center, title=f"Move “{self.entry.title}” to Deleted?",
                                 body="It stays in Deleted for 30 days.", action="Move to Deleted",
                                 on_confirm=self._delete)

    def _delete(self):
        e = self.entry
        self.flush()
        self.library.delete(e)
        self.close_file()
        self.refresh()
        Toast.show(self.host, "Moved to Deleted", kind="deleted", undo=lambda: self._restore(e))

    def _restore(self, e):
        self.library.restore(e)
        self.refresh()
        self.open_entry(e)
        Toast.show(self.host, "Restored", kind="undone")

    def _remove_forever(self):
        e = self.entry
        DestructiveDialog.in_bar(self.center, title=f"Delete “{e.title}” now?",
                                 body="This can't be undone.", action="Delete now",
                                 on_confirm=lambda: (self.library.remove(e), self.close_file(), self.refresh(),
                                                     Toast.show(self.host, "Deleted", kind="deleted")))

    # ------------------------------------------------------------ files in and out (portals)
    def open_file(self):
        ask_for_file(self, FileRequest("Open a document, spreadsheet or presentation", start="documents",
                                       show="documents", many=True), self._opened)

    def _opened(self, files):
        if not files:
            return
        last = None
        for f in files:
            try:
                ok, data, _ = f.load_contents(None)
                last = self.library.import_bytes(bytes(data), f.get_basename() or "Untitled")
            except Exception as ex:
                Toast.show(self.host, f"Couldn't open “{f.get_basename()}”: {ex}", kind="error")
        if last:
            self.place = "all"
            self.query = ""
            self.open_entry(last)
            self.refresh()
            Toast.show(self.host, f"Opened “{last.title}”" if len(files) == 1 else f"Opened {len(files)} files",
                       kind="opening")

    def _write_out(self, f: Gio.File, data: bytes, what: str):
        try:
            f.replace_contents(data, None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
            Toast.show(self.host, f"Saved “{f.get_basename()}”", kind="saved")
        except GLib.Error as ex:
            Toast.show(self.host, f"Couldn't save {what}: {ex.message}", kind="error")

    def save_copy(self):
        if self.entry is None:
            return
        self.flush()
        ext = odf.EXT[self.kind]
        ask_for_file(self, FileRequest("Save a copy", mode="save", start="documents", name=self.entry.title + ext),
                     self._save_copy_to)

    def _save_copy_to(self, files):
        if not files:
            return
        f = files[0]
        name = (f.get_basename() or "").lower()
        model = self.current_model()
        import io
        if name.endswith(".csv") and self.kind == "spreadsheet":
            data = odf.model_to_csv(model, self.grid.sheet).encode()
        elif name.endswith((".md", ".markdown")) and self.kind == "document":
            data = odf.model_to_markdown(model).encode()
        elif name.endswith(".txt") and self.kind == "document":
            data = odf.model_text(model).encode()
        else:
            buf = io.BytesIO()
            odf.save(buf, model, self.entry.title)
            data = buf.getvalue()
        self._write_out(f, data, "the copy")

    def export_pdf(self):
        if self.entry is None:
            return
        self.flush()
        ask_for_file(self, FileRequest("Export as PDF", mode="save", start="documents", name=self.entry.title + ".pdf"),
                     self._export_to)

    def _export_to(self, files):
        if not files:
            return
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=GLib.get_user_cache_dir())
        os.close(fd)
        try:
            render.write_pdf(tmp, self.current_model(), self.entry.title,
                             self.grid.sheet if self.kind == "spreadsheet" else 0)
            with open(tmp, "rb") as fh:
                self._write_out(files[0], fh.read(), "the PDF")
        except Exception as ex:
            Toast.show(self.host, f"Couldn't export: {ex}", kind="error")
        finally:
            os.unlink(tmp)

    def _share(self, anchor):
        """Share = a PDF through the system's share sheet."""
        self.export_pdf()

    def print_file(self):
        if self.entry is None:
            return
        model = self.current_model()
        lay = render.layout_for(model, self.grid.sheet if self.kind == "spreadsheet" else 0)
        op = Gtk.PrintOperation(job_name=self.entry.title, embed_page_setup=True)
        setup = Gtk.PageSetup()
        if self.kind == "presentation":
            setup.set_orientation(Gtk.PageOrientation.LANDSCAPE)
        op.set_default_page_setup(setup)

        def begin(op_, ctx):
            op_.set_n_pages(lay.paginate(ctx.get_cairo_context()))

        def draw(op_, ctx, n):
            cr = ctx.get_cairo_context()
            sx, sy = ctx.get_width() / lay.size[0], ctx.get_height() / lay.size[1]
            s = min(sx, sy)
            cr.scale(s, s)
            lay.draw(cr, n)
        op.connect("begin-print", begin)
        op.connect("draw-page", draw)
        try:
            op.run(Gtk.PrintOperationAction.PRINT_DIALOG, self)
        except GLib.Error as ex:
            Toast.show(self.host, f"Couldn't print: {ex.message}", kind="error")

    def present_slides(self):
        if self.kind != "presentation":
            return
        from .slides import Presenter
        Presenter(self, self.editor.model, self.editor.index).present()

    # ------------------------------------------------------------ undo, find
    def undo(self):
        if self.editor is None:
            return
        if self.kind == "spreadsheet":
            self.grid.undo()
        else:
            self.editor.undo()

    def redo(self):
        if self.editor is None:
            return
        if self.kind == "spreadsheet":
            self.grid.redo()
        else:
            self.editor.redo()

    def find(self):
        if self.kind != "document":
            return
        from luma_appkit import ActionEditor, TextField
        find = TextField("Find", placeholder="Words to find", on_activate=lambda t: self._find_next(t))
        repl = TextField("Replace with", placeholder="Leave empty to delete them")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(find)
        box.append(repl)
        self.center.set_editor(ActionEditor("Find and replace", "search", body=box,
                                            tools=[BarAction("search", "Find next", on_activate=lambda: self._find_next(find.text))],
                                            primary=BarAction("replace", "Replace all",
                                                              on_activate=lambda: self._replace_all(find.text, repl.text))))
        self.center.grow()
        GLib.idle_add(lambda: find.grab_focus() and False)

    def _find_next(self, text):
        if not self.editor.find(text):
            Toast.show(self.host, "No matches", kind="warning")

    def _replace_all(self, a, b):
        n = self.editor.replace_all(a, b)
        self.center.fold()
        Toast.show(self.host, f"Replaced {n} match" + ("" if n == 1 else "es") if n else "No matches",
                   kind="done" if n else "warning")

    # ------------------------------------------------------------ the bar
    def show_bar(self):
        new_menu = [MenuItem("Document", icon="file-text", on_activate=lambda: self.new_file("document")),
                    MenuItem("Spreadsheet", icon="table", on_activate=lambda: self.new_file("spreadsheet")),
                    MenuItem("Presentation", icon="monitor", on_activate=lambda: self.new_file("presentation")),
                    MenuItem("From a template…", icon="layout-template", note=None if self.pro else "Pro",
                             on_activate=self.ask_template)]
        if self.entry is None:
            self.center.show_bar([BarAction("folder-open", "Open…", on_activate=self.open_file),
                                  BarAction("square-pen", "New", menu=new_menu, primary=True)])
            return
        if self.entry.deleted:
            e = self.entry
            self.center.show_bar([BarAction("trash-2", "Delete now", danger=True, on_activate=self._remove_forever),
                                  BarAction("undo-2", "Restore", primary=True, on_activate=lambda: self._restore(e))])
            return
        if self.kind == "document":
            self._writer_bar()
        elif self.kind == "spreadsheet":
            self._sheet_bar()
        else:
            self._slides_bar()

    def _writer_bar(self):
        w = self.editor
        self.center.show_bar([
            w.style_menu,
            BarAction("bold", tooltip="Bold", on_activate=lambda: w.toggle_mark("b")),
            BarAction("italic", tooltip="Italic", on_activate=lambda: w.toggle_mark("i")),
            BarAction("underline", tooltip="Underline", on_activate=lambda: w.toggle_mark("u")),
            BarAction("list", tooltip="Bulleted list", on_activate=lambda: w.set_kind("bullet")),
            BarAction("list-ordered", tooltip="Numbered list", on_activate=lambda: w.set_kind("number")),
            BarAction("text-align-start", tooltip="Alignment", menu=w.align_rows),
        ], more=[
            BarAction("undo-2", "Undo", on_activate=w.undo),
            BarAction("redo", "Redo", on_activate=w.redo),
            BarAction("strikethrough", "Strikethrough", on_activate=lambda: w.toggle_mark("s")),
            BarAction("calendar", "Insert today's date", on_activate=w.insert_date),
            BarAction("search", "Find and replace…", on_activate=self.find),
            BarAction("file-text", "Page size: " + ("Letter" if w.page_size == "letter" else "A4"),
                      on_activate=self._toggle_page),
            BarAction("file-text", "Header, footer and page numbers…", on_activate=self.ask_page_setup),
            BarAction("history", "Version history…", on_activate=self.ask_versions),
            BarAction("sparkles", f"{PRO}…", on_activate=self.open_pro),
            BarAction("download", "Check for updates…", on_activate=lambda: self.updater.open()),
        ])

    def _toggle_page(self):
        w = self.editor
        w.page_size = "a4" if w.page_size == "letter" else "letter"
        self._edited()
        self.show_bar()
        Toast.show(self.host, "Page size set to " + ("A4" if w.page_size == "a4" else "Letter"), kind="done")

    # ---- spreadsheet
    def _sheet_page(self, model):
        from .sheet import SheetView
        touch = getattr(getattr(self, "context", None), "input", None)
        self.grid = SheetView(model, touch=str(touch).lower().endswith("touch"))
        self.grid.connect("changed", self._edited)
        self.grid.connect("selection-changed", lambda *_: self._sheet_selection())
        self.grid.connect("edit-requested", self._sheet_edit)
        page = Gtk.Grid(hexpand=True, vexpand=True)
        page.attach(self.grid, 0, 0, 1, 1)
        vbar = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=self.grid.vadj)
        hbar = Gtk.Scrollbar(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.grid.hadj)
        page.attach(vbar, 1, 0, 1, 1)
        page.attach(hbar, 0, 1, 1, 1)
        hbar.set_margin_bottom(96)  # stay clear of the floating bar
        page.grid = self.grid
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._sheet_keys)
        self.grid.add_controller(keys)
        return page

    def _sheet_keys(self, _c, keyval, _code, state):
        from gi.repository import Gdk
        if not state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if keyval in (Gdk.KEY_c, Gdk.KEY_x):
            text = self.grid.copy_text()
            self.get_clipboard().set(text)
            self._clipboard_origin = (text, self.grid.selection()[:2])
            if keyval == Gdk.KEY_x:
                self.grid.apply_to_selection(lambda i: i.pop("v", None), "Cut")
            Toast.show(self.host, "Copied" if keyval == Gdk.KEY_c else "Cut", kind="copied")
            return True
        if keyval == Gdk.KEY_v:
            self.get_clipboard().read_text_async(None, self._pasted)
            return True
        if keyval == Gdk.KEY_b:
            self.grid.set_bold(not self.grid.info(*self.grid.cur).get("b"))
            return True
        if keyval == Gdk.KEY_i:
            self.grid.set_italic(not self.grid.info(*self.grid.cur).get("i"))
            return True
        if keyval == Gdk.KEY_d:
            self.grid.fill_down()
            return True
        return False

    def _pasted(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            text = None
        if not text:
            return
        origin = self._clipboard_origin[1] if self._clipboard_origin and self._clipboard_origin[0] == text else None
        self.grid.paste_text(text, origin)

    def _sheet_edit(self, _grid, text):
        entry = getattr(self, "_formula", None)
        if entry is None:
            return
        if text.startswith("\0"):
            entry.set_text(text[1:])
        else:
            entry.set_text(text)
        entry.focus()

    def _sheet_selection(self):
        entry = getattr(self, "_formula", None)
        if entry is None:
            return
        g = self.grid
        entry.set_text(g.raw())
        entry.set_placeholder(f"{g.selection_name()} · type a value or =formula")
        self._sheet_name_label()

    def _formula_submit(self, text):
        g = self.grid
        r, c = g.cur
        g.set_raw(r, c, text)
        g.select(r + 1, c)
        g.grab_focus()

    def _sheet_name_label(self):
        pass

    def _sheet_bar(self):
        g = self.grid
        self._formula = BarEntry("quick", label="Cell contents", icon="square-function",
                                 placeholder=f"{g.selection_name()} · type a value or =formula", text=g.raw(),
                                 grows=False, on_submit=self._formula_submit,
                                 on_close=lambda: g.grab_focus())
        names = g.sheet_names()
        sheet_menu = [MenuItem(n, icon="table", selected=(i == g.sheet), on_activate=lambda i=i: self._go_sheet(i))
                      for i, n in enumerate(names)] + [None,
                     MenuItem("Add sheet", icon="plus", on_activate=self._add_sheet)]
        self.center.show_bar([
            BarMenu(names[g.sheet], sheet_menu, icon="table", name="Sheet"),
            BarAction("sigma", tooltip="Sum", on_activate=self._autosum),
            BarAction("bold", tooltip="Bold", on_activate=lambda: g.set_bold(not g.info(*g.cur).get("b"))),
            BarAction("percent", tooltip="Number format", menu=lambda: g.format_rows()),
            BarAction("text-align-start", tooltip="Alignment", menu=g.align_rows),
            BarAction("arrow-down-a-z", tooltip="Sort A to Z", on_activate=lambda: self._sort(False)),
        ], entry=self._formula, more=[
            BarAction("undo-2", "Undo", on_activate=g.undo),
            BarAction("redo", "Redo", on_activate=g.redo),
            BarAction("italic", "Italic", on_activate=lambda: g.set_italic(not g.info(*g.cur).get("i"))),
            BarAction("arrow-up-down", "Sort Z to A", on_activate=lambda: self._sort(True)),
            BarAction("between-horizontal-end", "Insert row above", on_activate=lambda: g.insert_rows(False)),
            BarAction("between-horizontal-end", "Insert row below", on_activate=lambda: g.insert_rows(True)),
            BarAction("between-vertical-end", "Insert column left", on_activate=lambda: g.insert_cols(False)),
            BarAction("between-vertical-end", "Insert column right", on_activate=lambda: g.insert_cols(True)),
            BarAction("arrow-down", "Fill down", on_activate=g.fill_down),
            BarAction("eraser", "Clear cells", on_activate=g.clear),
            BarAction("minus", "Delete rows", danger=True, on_activate=g.delete_rows),
            BarAction("minus", "Delete columns", danger=True, on_activate=g.delete_cols),
            BarAction("edit-rename", "Rename sheet…", on_activate=self._ask_rename_sheet),
            BarAction("trash-2", "Delete sheet", danger=True, on_activate=self._ask_delete_sheet),
            BarAction("history", "Version history…", on_activate=self.ask_versions),
            BarAction("sparkles", f"{PRO}…", on_activate=self.open_pro),
        ])

    def _go_sheet(self, i):
        self.grid.set_sheet(i)
        self._sheet_bar()

    def _add_sheet(self):
        i = self.grid.add_sheet()
        self._go_sheet(i)
        Toast.show(self.host, f"Added “{self.grid.sheet_names()[i]}”", kind="added")

    def _ask_rename_sheet(self):
        from luma_appkit import ActionEditor, TextField
        g = self.grid
        field = TextField("Sheet name", value=g.sheet_names()[g.sheet])

        def done(*_):
            self.center.fold()
            if g.rename_sheet(field.text):
                self._sheet_bar()
                Toast.show(self.host, "Sheet renamed", kind="done")
            else:
                Toast.show(self.host, "That name is empty or already used", kind="warning")
        self.center.set_editor(ActionEditor("Rename sheet", "edit-rename", body=field,
                                            primary=BarAction("check", "Rename", on_activate=done),
                                            submit_on_return=True))
        self.center.grow()

    def _ask_delete_sheet(self):
        g = self.grid
        if len(g.sheet_names()) < 2:
            Toast.show(self.host, "A spreadsheet keeps at least one sheet", kind="warning")
            return
        name = g.sheet_names()[g.sheet]
        DestructiveDialog.in_bar(self.center, title=f"Delete “{name}”?", body="Its cells go with it.",
                                 action="Delete sheet", on_confirm=self._delete_sheet)

    def _delete_sheet(self):
        gone = self.grid.delete_sheet()
        self._sheet_bar()
        if gone is not None:
            Toast.show(self.host, f"Deleted “{gone['name']}”", kind="deleted")

    def _autosum(self):
        g = self.grid
        f = g.autosum()
        r1, c1, r2, c2 = g.selection()
        if (r1, c1) != (r2, c2):  # a range selected: the total goes under it
            g.select(r2 + 1, c1)
        self._formula.set_text(f)
        self._formula.focus()

    def _sort(self, descending):
        self.grid.sort(descending)
        Toast.show(self.host, "Sorted " + ("Z to A" if descending else "A to Z"), kind="done")

    # ---- presentation
    def _slides_bar(self):
        s = self.editor
        n = len(s.model["slides"])
        from luma_appkit import BarReadout
        self.center.show_bar([
            BarReadout(f"{s.index + 1} of {n}", label="Slide", on_previous=lambda: s.show_slide(s.index - 1),
                       on_next=lambda: s.show_slide(s.index + 1)),
            BarAction("layout-template", tooltip="Layout", menu=s.layout_rows),
            BarAction("palette", tooltip="Theme", menu=s.theme_rows),
            BarAction("plus", "New slide", primary=True, on_activate=lambda: s.add_slide()),
        ], more=[
            BarAction("undo-2", "Undo", on_activate=s.undo),
            BarAction("redo", "Redo", on_activate=s.redo),
            BarAction("copy", "Duplicate slide", on_activate=s.duplicate_slide),
            BarAction("chevron-up", "Move slide earlier", on_activate=lambda: s.move_slide(-1)),
            BarAction("chevron-down", "Move slide later", on_activate=lambda: s.move_slide(1)),
            BarAction("trash-2", "Delete slide", danger=True, on_activate=self._delete_slide),
            BarAction("play", "Present", on_activate=self.present_slides),
            BarAction("history", "Version history…", on_activate=self.ask_versions),
            BarAction("sparkles", f"{PRO}…", on_activate=self.open_pro),
        ])

    def _delete_slide(self):
        if self.editor.delete_slide():
            Toast.show(self.host, "Slide deleted", kind="deleted", undo=self.editor.undo)
        else:
            Toast.show(self.host, "A presentation keeps at least one slide", kind="warning")


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)

    def do_activate(self):
        win = self.props.active_window or (self.get_windows() or [None])[0] or Window(self)
        win.present()
        shot = os.environ.get("APP_SHOT")
        if shot:
            from .shots import schedule
            schedule(win, shot)

    def do_open(self, files, n_files, hint):
        self.do_activate()
        self.props.active_window._opened(list(files))


def main(argv=None):
    return App().run(argv if argv is not None else sys.argv)
