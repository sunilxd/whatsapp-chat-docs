"""Fallback for unrooted phones without an E2E backup key: parse the .txt from
WhatsApp's "Export chat -> Include media" and collect attached file names."""
from __future__ import annotations

import io
import re
import zipfile

# "12/03/24, 10:15 - Name: body"  or  "[12/03/24, 10:15:02] Name: body"
_LINE = re.compile(
    r"^‎?\[?(?P<date>\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?[Mm]\.?)?)\]?"
    r"\s(?:-\s)?(?P<sender>[^:]+):\s(?P<body>.*)$"
)
_ANDROID = re.compile(r"^‎?(?P<name>.+?)\s\((?:file attached|archivo adjunto|arquivo anexado|fichier joint|Datei angehängt)\)")
_IOS = re.compile(r"<attached:\s(?:\d{8}-)?(?P<name>[^>]+)>")


def attachments(data: bytes, filename: str = "") -> list[dict]:
    """Return [{'date', 'time', 'sender', 'file_name'}] from an export .txt or .zip."""
    if filename.lower().endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            txt = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
            if not txt:
                raise ValueError("No .txt chat file inside the zip.")
            data = z.read(txt)
    text = data.decode("utf-8-sig", errors="replace")

    found = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        body = m["body"]
        a = _ANDROID.match(body) or _IOS.search(body)
        if a:
            found.append({
                "date": m["date"], "time": m["time"],
                "sender": m["sender"].strip(), "file_name": a["name"].strip(),
            })
    return found
