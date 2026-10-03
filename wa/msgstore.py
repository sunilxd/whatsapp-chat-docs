"""Decrypt WhatsApp backups (via wa-crypt-tools) and query chats/documents."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd

DOCUMENT_TYPE = 9  # message.message_type for documents


def _wadecrypt() -> str:
    exe_dir = Path(sys.executable).parent
    for c in (
        shutil.which("wadecrypt"),
        exe_dir / "wadecrypt.exe", exe_dir / "Scripts" / "wadecrypt.exe",
        exe_dir / "wadecrypt",
    ):
        if c and Path(c).is_file():
            return str(c)
    raise RuntimeError("`wadecrypt` not found. Run: pip install wa-crypt-tools")


def decrypt_backup(encrypted: Path, key: str, out_db: Path) -> Path:
    """`key` is the 64-hex-digit E2E backup key or a path to a key file."""
    key = key.strip()
    if not Path(key).is_file():
        key = "".join(key.split()).lower()
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("The backup key must be 64 hexadecimal characters.")
    proc = subprocess.run(
        [_wadecrypt(), key, str(encrypted), str(out_db)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not out_db.exists():
        raise RuntimeError("Decryption failed:\n" + (proc.stderr or proc.stdout))
    return out_db


def _connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = {"message", "message_media", "chat", "jid"} - tables
    if missing:
        con.close()
        raise RuntimeError(
            f"Unsupported msgstore.db schema (missing tables: {', '.join(sorted(missing))}). "
            "Update WhatsApp and create a fresh backup."
        )
    return con


def list_chats(db: Path) -> pd.DataFrame:
    """Chats that contain at least one document, busiest first."""
    with _connect(db) as con:
        return pd.read_sql_query(
            """
            SELECT c._id AS chat_id,
                   COALESCE(NULLIF(c.subject, ''), j.user, j.raw_string) AS name,
                   j.raw_string AS jid,
                   COUNT(m._id) AS documents,
                   MAX(m.timestamp) AS last_ts
            FROM chat c
            JOIN jid j ON j._id = c.jid_row_id
            JOIN message m ON m.chat_row_id = c._id AND m.message_type = ?
            GROUP BY c._id
            ORDER BY last_ts DESC
            """,
            con, params=(DOCUMENT_TYPE,),
        )


def list_documents(db: Path, chat_id: int) -> pd.DataFrame:
    with _connect(db) as con:
        df = pd.read_sql_query(
            """
            SELECT m._id AS message_id,
                   m.timestamp AS ts,
                   m.from_me,
                   COALESCE(s.user, s.raw_string) AS sender,
                   mm.file_path,
                   mm.file_size,
                   mm.mime_type,
                   mm.media_name,
                   m.text_data AS caption
            FROM message m
            JOIN message_media mm ON mm.message_row_id = m._id
            LEFT JOIN jid s ON s._id = m.sender_jid_row_id
            WHERE m.chat_row_id = ? AND m.message_type = ?
            ORDER BY m.timestamp
            """,
            con, params=(chat_id, DOCUMENT_TYPE),
        )
    # NULLs come back as NaN (a truthy float); make text columns use None instead.
    text_cols = ["sender", "file_path", "mime_type", "media_name", "caption"]
    df[text_cols] = df[text_cols].astype(object).where(df[text_cols].notna(), None)
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(None)
    return df
