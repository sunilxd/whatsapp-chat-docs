# WhatsApp Chat Documents → PC

A local Streamlit app that copies WhatsApp **documents from one chosen chat** off an
Android phone connected over ADB.

## Why it needs the message database

WhatsApp saves every received document into one shared folder
(`Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Documents`), with no per-chat
sub-folders. The only record of which file came from which chat is WhatsApp's message
database, `msgstore.db`. The app gets that database in one of these ways:

| Source | Needs | Accuracy |
|---|---|---|
| **Encrypted backup + 64-digit key** (recommended) | Turn on end-to-end encrypted backup with a 64-digit key in WhatsApp, then tap *Back up* | Exact |
| **Rooted device** | Root (`su`) | Exact, live data |
| **Already-decrypted msgstore.db** | A database you decrypted elsewhere | Exact |
| **Chat export .txt/.zip** | WhatsApp's *Export chat → Include media* | Matched by file name only |

Backups are decrypted with [wa-crypt-tools](https://github.com/ElDavoo/wa-crypt-tools).
Everything stays on your PC. The decrypted database is written to your temp folder
(`%TEMP%\wa_chat_docs`).

## Setup

1. Install [Android platform-tools](https://developer.android.com/tools/releases/platform-tools)
   (`adb`). Add it to PATH, or paste the path to `adb` into the app's sidebar.
2. On the phone, turn on **Developer options → USB debugging**, connect the phone by USB,
   and accept the prompt.
3. Install and run:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\streamlit run app.py
```

The app opens at http://localhost:8501.

## Using it

1. In the sidebar, pick the device, the app (WhatsApp or WhatsApp Business), and the folder to copy into.
2. Load the chat list from one of the sources above.
3. Pick the chat. You can search by group name or phone number. The database has no contact
   names, so one-to-one chats appear as phone numbers.
4. Choose which documents to copy (filter by date or name), then click **Copy**. Files go into
   `<destination>/<chat name>/`. Each file keeps its original timestamp, and files already
   copied are skipped.

Documents that were deleted from the phone, or never downloaded, show as *not on phone*
and can't be copied.
