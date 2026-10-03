"""WhatsApp-on-device layout: where documents and backups live, and how to
map a database `file_path` back to a real file on the phone."""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from .adb import Adb, RemoteFile, shell_quote

APPS = {
    "WhatsApp": ("com.whatsapp", "WhatsApp"),
    "WhatsApp Business": ("com.whatsapp.w4b", "WhatsApp Business"),
}


def roots(app: str) -> list[str]:
    """WhatsApp storage roots: scoped storage (Android 11+) first, then legacy."""
    pkg, folder = APPS[app]
    return [f"/sdcard/Android/media/{pkg}/{folder}", f"/sdcard/{folder}"]


def documents_dirs(app: str) -> list[str]:
    folder = APPS[app][1]
    return [f"{r}/Media/{folder} Documents" for r in roots(app)]


@dataclass
class DocumentIndex:
    """Every document file currently on the device, indexed for lookup."""
    files: list[RemoteFile] = field(default_factory=list)
    by_rel: dict[str, RemoteFile] = field(default_factory=dict)
    by_name: dict[str, list[RemoteFile]] = field(default_factory=dict)

    @classmethod
    def scan(cls, adb: Adb, app: str) -> "DocumentIndex":
        idx = cls()
        for d in documents_dirs(app):
            for f in adb.list_files(d):
                idx.files.append(f)
                rel = _rel_from_media(f.path)
                if rel:
                    idx.by_rel.setdefault(rel, f)
                idx.by_name.setdefault(f.name.lower(), []).append(f)
        return idx

    def resolve(self, file_path: str | None, name_hint: str | None = None) -> RemoteFile | None:
        """Find the device file for a DB `file_path` (relative or absolute)."""
        if isinstance(file_path, str) and file_path:
            rel = _rel_from_media(file_path)
            if rel and rel in self.by_rel:
                return self.by_rel[rel]
            hit = self.by_name.get(posixpath.basename(file_path.replace("\\", "/")).lower())
            if hit:
                return hit[0]
        if isinstance(name_hint, str) and name_hint:
            hit = self.by_name.get(name_hint.lower())
            if hit:
                return hit[0]
        return None


def _rel_from_media(path: str) -> str | None:
    p = path.replace("\\", "/")
    i = p.lower().find("media/")
    return p[i:].lower() if i >= 0 else None


def latest_backup(adb: Adb, app: str) -> RemoteFile | None:
    """Most recent msgstore*.crypt14/15 backup on shared storage."""
    candidates = []
    for r in roots(app):
        for f in adb.list_files(f"{r}/Databases"):
            if f.name.startswith("msgstore") and ".crypt1" in f.name:
                candidates.append(f)
    # Prefer the live "msgstore.db.cryptNN" over dated copies, then newest.
    candidates.sort(key=lambda f: (f.name.startswith("msgstore.db."), f.mtime), reverse=True)
    return candidates[0] if candidates else None


def pull_db_rooted(adb: Adb, app: str, dest_dir: Path) -> Path:
    """Copy the unencrypted msgstore.db (+ WAL) out of /data via `su`."""
    pkg = APPS[app][0]
    tmp = "/sdcard/Download/.wa_msgstore_tmp"
    src = f"/data/data/{pkg}/databases"
    out = adb.shell(
        f"su -c \"mkdir -p {tmp} && cp {src}/msgstore.db* {tmp}/ && chmod 644 {tmp}/*\" && echo OK"
    )
    if "OK" not in out:
        raise RuntimeError("Root copy failed. Is the device rooted and is shell granted su access?\n" + out)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        for f in adb.list_files(tmp):
            adb.pull(f.path, dest_dir / f.name)
    finally:
        adb.shell(f"rm -rf {shell_quote(tmp)}")
    db = dest_dir / "msgstore.db"
    if not db.exists():
        raise RuntimeError("msgstore.db was not found in the app data directory.")
    return db
