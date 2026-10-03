"""Streamlit app: copy WhatsApp documents from ONE chat off an Android phone.

Run:  streamlit run app.py
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from wa import chat_export, msgstore, whatsapp
from wa.adb import Adb, AdbError, find_adb

st.set_page_config(page_title="WhatsApp Chat Documents", page_icon="📄", layout="wide")
ss = st.session_state
WORK = Path(tempfile.gettempdir()) / "wa_chat_docs"
WORK.mkdir(exist_ok=True)

SOURCES = [
    "Encrypted backup + 64-digit key (no root)",
    "Rooted device",
    "Already-decrypted msgstore.db",
    "Chat export .txt/.zip (fallback)",
]


def human(n: float | None) -> str:
    if n is None or pd.isna(n):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .") or "chat"


@st.cache_data(show_spinner=False)
def cached_chats(db: str, mtime: float) -> pd.DataFrame:
    return msgstore.list_chats(Path(db))


@st.cache_data(show_spinner=False)
def cached_documents(db: str, mtime: float, chat_id: int) -> pd.DataFrame:
    return msgstore.list_documents(Path(db), chat_id)


# ---------------------------------------------------------------- sidebar ---
with st.sidebar:
    st.header("1. Phone")
    adb_path = st.text_input("adb executable", value=find_adb() or "",
                             help="Android platform-tools adb. Leave as detected if found.")
    if not adb_path or not Path(adb_path).is_file():
        st.error("adb not found. Install Android platform-tools and enter the path to adb.")
        st.stop()
    st.button("Refresh devices")
    try:
        devices = Adb(adb_path).devices()
    except (AdbError, OSError) as e:
        st.error(f"adb failed: {e}")
        st.stop()
    for d in devices:
        if d.state == "unauthorized":
            st.warning(f"{d.serial}: unlock the phone and accept the USB-debugging prompt.")
    ready = [d for d in devices if d.state == "device"]
    if not ready:
        st.info("Connect the phone by USB with **Developer options → USB debugging** enabled.")
        st.stop()
    device = st.selectbox("Device", ready, format_func=lambda d: d.label)
    app = st.selectbox("App", list(whatsapp.APPS))
    dest_root = st.text_input("Copy into folder",
                              str(Path.home() / "Downloads" / "WhatsApp Chat Documents"))
    rescan = st.button("Rescan documents on phone")

adb = Adb(adb_path, device.serial)
dev_work = WORK / safe_name(device.serial)
dev_work.mkdir(exist_ok=True)

index_key = (device.serial, app)
if rescan or ss.get("index_key") != index_key:
    with st.spinner("Scanning WhatsApp Documents folder on the phone..."):
        ss.index = whatsapp.DocumentIndex.scan(adb, app)
        ss.index_key = index_key
        ss.pop("db", None)
        ss.pop("export", None)
index: whatsapp.DocumentIndex = ss.index
st.sidebar.caption(f"{len(index.files)} document files on the phone "
                   f"({human(sum(f.size for f in index.files))}).")

# ----------------------------------------------------------- chat source ---
st.title("📄 WhatsApp chat documents → PC")
st.header("2. Load the chat list")
source = st.radio("How should chats be identified?", SOURCES, horizontal=True,
                  label_visibility="collapsed")

if source == SOURCES[0]:
    st.markdown(
        "On the phone: **WhatsApp → Settings → Chats → Chat backup → End-to-end encrypted backup** "
        "→ turn on with *Use 64-digit encryption key* (save the key). Then tap **Back up** so the "
        "backup includes the latest messages."
    )
    backup = whatsapp.latest_backup(adb, app)
    if backup:
        st.caption(f"Backup found: `{backup.path}` · {human(backup.size)} · "
                   f"{pd.to_datetime(backup.mtime, unit='s')} UTC")
    else:
        st.warning("No msgstore backup found on the phone. Run a WhatsApp backup first.")
    c1, c2 = st.columns([2, 1])
    key = c1.text_input("64-digit backup key", type="password")
    keyfile = c2.file_uploader("…or a key file (crypt14 `key`)", type=None)
    if st.button("Pull & decrypt backup", disabled=not backup or not (key or keyfile), type="primary"):
        with st.spinner("Pulling and decrypting backup…"):
            try:
                enc = dev_work / backup.name
                adb.pull(backup.path, enc)
                if keyfile:
                    kp = dev_work / "key"
                    kp.write_bytes(keyfile.getvalue())
                    key = str(kp)
                ss.db = msgstore.decrypt_backup(enc, key, dev_work / "msgstore.db")
                enc.unlink(missing_ok=True)
            except Exception as e:
                st.error(str(e))

elif source == SOURCES[1]:
    st.markdown("Copies the live `msgstore.db` from app data using `su`. Grant root to *Shell* when prompted.")
    if st.button("Pull database (root)", type="primary"):
        with st.spinner("Copying database…"):
            try:
                ss.db = whatsapp.pull_db_rooted(adb, app, dev_work / "root")
            except Exception as e:
                st.error(str(e))

elif source == SOURCES[2]:
    up = st.file_uploader("msgstore.db", type=["db", "sqlite"])
    if up and st.button("Use this database", type="primary"):
        p = dev_work / "uploaded_msgstore.db"
        p.write_bytes(up.getvalue())
        ss.db = p

else:
    st.markdown(
        "Open the chat on the phone → **⋮ → More → Export chat → Include media**, save the zip "
        "and upload it (or just the .txt) here. Attached file names are matched against the "
        "phone's WhatsApp Documents folder by name — less precise than the database options."
    )
    up = st.file_uploader("Chat export", type=["txt", "zip"])
    if up:
        try:
            ss.export = (Path(up.name).stem, chat_export.attachments(up.getvalue(), up.name))
        except Exception as e:
            st.error(str(e))

# --------------------------------------------------------- pick the chat ---
rows: list[dict] = []
chat_name = ""

if source != SOURCES[3] and ss.get("db"):
    db: Path = ss.db
    try:
        chats = cached_chats(str(db), db.stat().st_mtime)
    except Exception as e:
        st.error(str(e))
        st.stop()
    if chats.empty:
        st.info("No chats with documents in this database.")
        st.stop()
    st.header("3. Pick the chat")
    labels = {r.chat_id: f"{r.name}  ·  {r.documents} docs  ·  {r.jid}" for r in chats.itertuples()}
    chat_id = st.selectbox("Chat (type to search by group name or phone number)",
                           list(labels), format_func=labels.get)
    chat_name = chats.loc[chats.chat_id == chat_id, "name"].iloc[0]
    docs = cached_documents(str(db), db.stat().st_mtime, int(chat_id))
    for r in docs.itertuples():
        f = index.resolve(r.file_path, r.media_name)
        rows.append({
            "date": r.date,
            "file_name": f.name if f else (r.media_name or Path(str(r.file_path or "")).name or "(unknown)"),
            "from": "me" if r.from_me else (r.sender or chat_name),
            "size": human(f.size if f else r.file_size),
            "on_phone": f is not None,
            "device_path": f.path if f else (r.file_path or ""),
        })

elif source == SOURCES[3] and ss.get("export"):
    chat_name, attached = ss.export
    chat_name = re.sub(r"^WhatsApp Chat (with|-)\s*", "", chat_name) or chat_name
    st.header("3. Documents in this chat")
    for a in attached:
        f = index.resolve(None, a["file_name"])
        rows.append({
            "date": f"{a['date']} {a['time']}",
            "file_name": a["file_name"],
            "from": a["sender"],
            "size": human(f.size) if f else "",
            "on_phone": f is not None,
            "device_path": f.path if f else "",
        })
    # Keep only attachments that are documents on the phone or don't look like photos/videos.
    rows = [r for r in rows if r["on_phone"]
            or not re.match(r"^(IMG|VID|PTT|AUD|STK)-\d{8}-WA\d+", r["file_name"], re.I)]

if not rows:
    if ss.get("db") or ss.get("export"):
        st.info("No documents found for this chat.")
    st.stop()

# -------------------------------------------------------- select & copy ---
df = pd.DataFrame(rows)
df.insert(0, "select", df["on_phone"])
missing = int((~df.on_phone).sum())
st.caption(f"{len(df)} documents · {len(df) - missing} still on the phone"
           + (f" · {missing} deleted/not downloaded (can't be copied)" if missing else ""))

if pd.api.types.is_datetime64_any_dtype(df["date"]) and len(df) > 1:
    lo, hi = df.date.min().date(), df.date.max().date()
    if lo < hi:
        d1, d2 = st.slider("Date range", lo, hi, (lo, hi))
        df = df[(df.date.dt.date >= d1) & (df.date.dt.date <= d2)]

query = st.text_input("Filter by file name", placeholder="e.g. .pdf or policy")
if query:
    df = df[df.file_name.str.contains(query, case=False, regex=False)]

edited = st.data_editor(
    df, hide_index=True, use_container_width=True,
    disabled=[c for c in df.columns if c != "select"],
    column_config={
        "select": st.column_config.CheckboxColumn("Copy", width="small"),
        "date": st.column_config.DatetimeColumn("Date", format="YYYY-MM-DD HH:mm")
        if pd.api.types.is_datetime64_any_dtype(df["date"]) else "Date",
        "on_phone": st.column_config.CheckboxColumn("On phone", width="small"),
        "device_path": st.column_config.TextColumn("Phone path", width="large"),
    },
)
chosen = edited[edited.select & edited.on_phone]
target_dir = Path(dest_root) / safe_name(str(chat_name))
st.write(f"**{len(chosen)}** selected → `{target_dir}`")

if st.button(f"Copy {len(chosen)} documents", type="primary", disabled=chosen.empty):
    target_dir.mkdir(parents=True, exist_ok=True)
    sizes = {f.path: f.size for f in index.files}
    bar = st.progress(0.0)
    copied = skipped = 0
    errors = []
    for i, r in enumerate(chosen.to_dict("records"), 1):
        name = safe_name(Path(r["device_path"]).name)
        target = target_dir / name
        if target.exists():
            if target.stat().st_size == sizes.get(r["device_path"]):
                skipped += 1
                bar.progress(i / len(chosen), text=f"Skipped (already copied) {name}")
                continue
            stem, suf, n = target.stem, target.suffix, 1
            while target.exists():
                target = target_dir / f"{stem} ({n}){suf}"
                n += 1
        try:
            adb.pull(r["device_path"], target)
            copied += 1
        except AdbError as e:
            errors.append(f"{name}: {e}")
        bar.progress(i / len(chosen), text=f"Copied {name}")
    st.success(f"Copied {copied}, skipped {skipped} already present → {target_dir}")
    for e in errors:
        st.error(e)
