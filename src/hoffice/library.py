# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Hartmann Office keeps its files.

Every file lives in the app's own data folder (inside the sandbox) as a real
OpenDocument file, with a small index for titles, kinds and dates. Deleted
files wait 30 days in Deleted before they are removed. Files from elsewhere
come in through the file chooser portal (Open) and go out the same way
(Save a copy, Export), so the app never needs access to your folders.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass

from gi.repository import GLib

from . import odf

__all__ = ["Entry", "Library", "KIND_NAMES", "KIND_ICONS"]

KIND_NAMES = {"document": "Document", "spreadsheet": "Spreadsheet", "presentation": "Presentation"}
KIND_ICONS = {"document": "file-text", "spreadsheet": "table", "presentation": "monitor"}
UNTITLED = {"document": "Untitled document", "spreadsheet": "Untitled spreadsheet",
            "presentation": "Untitled presentation"}
KEEP_DELETED_S = 30 * 86400


@dataclass
class Entry:
    id: str
    kind: str
    title: str
    created: float
    modified: float
    deleted: float = 0.0
    preview: str = ""

    @property
    def filename(self) -> str:
        return self.id + odf.EXT[self.kind]


class Library:
    def __init__(self, root: str | None = None):
        self.root = root or os.path.join(GLib.get_user_data_dir(), "hartmann-office")
        self.files = os.path.join(self.root, "files")
        self.index_path = os.path.join(self.root, "index.json")
        os.makedirs(self.files, exist_ok=True)
        self.entries: dict[str, Entry] = {}
        self._load_index()
        self.purge()

    # ------------------------------------------------------------ index
    def _load_index(self):
        try:
            with open(self.index_path, encoding="utf-8") as f:
                raw = json.load(f)
            for e in raw.get("entries", []):
                if e.get("kind") in odf.KINDS:
                    entry = Entry(**{k: e[k] for k in Entry.__dataclass_fields__ if k in e})
                    if os.path.exists(self.path(entry)):
                        self.entries[entry.id] = entry
        except (OSError, ValueError, TypeError):
            self.entries = {}
        # Files on disk the index forgot (a crash between writes) come back.
        for name in os.listdir(self.files):
            stem, ext = os.path.splitext(name)
            kind = {v: k for k, v in odf.EXT.items()}.get(ext)
            if kind and stem not in self.entries and not name.startswith("."):
                st = os.stat(os.path.join(self.files, name))
                self.entries[stem] = Entry(stem, kind, UNTITLED[kind], st.st_mtime, st.st_mtime)

    def _save_index(self):
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": [asdict(e) for e in self.entries.values()]}, f, ensure_ascii=False)
        os.replace(tmp, self.index_path)

    def path(self, entry: Entry) -> str:
        return os.path.join(self.files, entry.filename)

    # ------------------------------------------------------------ queries
    def list(self, kind: str | None = None, *, deleted: bool = False, query: str = "") -> list[Entry]:
        q = query.strip().lower()
        out = [e for e in self.entries.values()
               if bool(e.deleted) == deleted and (kind is None or e.kind == kind)
               and (not q or q in e.title.lower() or q in e.preview.lower())]
        return sorted(out, key=lambda e: e.deleted if deleted else e.modified, reverse=True)

    def get(self, entry_id: str) -> Entry | None:
        return self.entries.get(entry_id)

    # ------------------------------------------------------------ changes
    def create(self, kind: str, title: str | None = None, model: dict | None = None) -> Entry:
        now = time.time()
        entry = Entry(uuid.uuid4().hex[:12], kind, title or UNTITLED[kind], now, now)
        self.entries[entry.id] = entry
        self.write(entry, model or odf.new_model(kind))
        return entry

    def read(self, entry: Entry) -> dict:
        return odf.load(self.path(entry), entry.filename)

    def write(self, entry: Entry, model: dict):
        tmp = os.path.join(self.files, "." + entry.filename + ".tmp")
        odf.save(tmp, model, entry.title)
        os.replace(tmp, self.path(entry))
        entry.modified = time.time()
        entry.preview = " ".join(odf.model_text(model).split())[:160]
        self._save_index()

    def rename(self, entry: Entry, title: str):
        title = " ".join(title.split())[:120]
        if title:
            entry.title = title
            entry.modified = time.time()
            self._save_index()

    def duplicate(self, entry: Entry) -> Entry:
        copy = self.create(entry.kind, f"{entry.title} copy", self.read(entry))
        return copy

    def delete(self, entry: Entry):
        entry.deleted = time.time()
        self._save_index()

    def restore(self, entry: Entry):
        entry.deleted = 0.0
        self._save_index()

    def remove(self, entry: Entry):
        try:
            os.remove(self.path(entry))
        except FileNotFoundError:
            pass
        self.entries.pop(entry.id, None)
        self._save_index()

    def purge(self):
        cut = time.time() - KEEP_DELETED_S
        for e in [e for e in self.entries.values() if e.deleted and e.deleted < cut]:
            self.remove(e)

    def import_bytes(self, data: bytes, name: str) -> Entry:
        model = odf.load(data, name)
        title = os.path.splitext(os.path.basename(name))[0] or UNTITLED[model["kind"]]
        return self.create(model["kind"], title, model)

    def reset(self):
        """Settings → Reset: remove every file and the index."""
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(self.files, exist_ok=True)
        self.entries = {}
        self._save_index()
