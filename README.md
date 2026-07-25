# 🎙️ EchoPad — The Private AI Notebook for Students & Young Professionals

[![CI](https://github.com/br24563/Echo-pad/actions/workflows/ci.yml/badge.svg)](https://github.com/br24563/Echo-pad/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Local-first](https://img.shields.io/badge/data-100%25%20local-brightgreen)
![Version](https://img.shields.io/badge/version-0.5.0-orange)

EchoPad turns your lectures, meetings, interviews, and study sessions into clean, structured notes — automatically, and without sending a single byte to the cloud.

Record straight from your browser (or upload a file), and EchoPad transcribes it locally with `faster-whisper`, then hands the transcript to a local LLM via `Ollama` to produce a polished, exam- and career-ready Markdown document. No API keys, no subscriptions, no data leaving your machine.

**Built for the way students and early-career professionals actually work:**
- 📚 Turn a recorded lecture into study-ready notes with key concepts, definitions, and self-check questions.
- 🧑‍💼 Turn a job interview (practice or real) into a structured debrief with strengths, gaps, and follow-up actions.
- 🤝 Turn a networking chat or career event into contact notes you'll actually remember to follow up on.
- 🗂️ Turn a team meeting or study group session into a TL;DR with clear action items and owners.

## 🚀 Features

| Feature | Why it matters |
|---|---|
| **100% Free & Offline** | No API keys, no subscriptions, no usage limits — runs entirely on your laptop. |
| **Private by Design** | Audio and transcripts never leave your machine — safe for confidential interviews, career coaching calls, or proprietary coursework. |
| **Purpose-Built Templates** | Twelve note formats across studying and work — Lecture, Reading, Lab Report, Problem Set, Meeting, One-on-One, Standup, Client Call, Interview, Performance Review Prep, Networking, Brainstorming — each tuned to what that context actually needs. |
| **📅 LMS Deadline Sync** | Connect your Canvas, Blackboard, or Moodle calendar feed and see every assignment due date in EchoPad — read-only, no password, no OAuth. Fully editable, and your edits survive re-syncing. |
| **📇 Flashcards & Spaced Repetition** | Turn any note into study cards, review them with Again/Good/Easy scheduling that brings back what you keep missing, and export to CSV for Anki or Quizlet. |
| **📖 Cross-Note Study Guides** | Merge a whole course's notes into one exam guide — grouped by theme, with a glossary, likely exam questions, and the topics your notes cover only thinly. |
| **✅ Action Item Tracking** | Every task in every meeting note, in one list, with owner and due date. Tick it off here and the note file is updated too, so the note stays the record of what's outstanding. |
| **✉️ Follow-Up Drafts** | Turn a meeting, interview, or networking note into a follow-up email that references what was actually discussed. |
| **🗓️ Weekly Digest** | Summarize the last 7/14/30 days across every note into a status update for a standup or 1:1. |
| **Live Mic, File Upload, or Import** | Record from your browser, upload `.mp3`/`.m4a`/`.wav`, or import notes you already have as PDF, Word, text, or a photo of the whiteboard. |
| **Full-Text Search** | Instantly find any past note by keyword — great for exam review or recalling "who was that contact from the career fair?" |
| **Tags & Dashboard** | Tag notes (e.g. `midterm`, `chapter-4`), browse by tag, and see a home dashboard with note counts per category and your most recently added notes. |
| **In-App Editing** | Refine AI-generated notes without leaving the app. |
| **Multi-Format Export** | Download any note as Markdown, HTML, or PDF for sharing or printing. |
| **Delete, With a Safety Net** | Every note has a Delete button that opens a confirmation dialog first — no accidental one-click data loss. |
| **Explorer-Friendly Storage** | Every note gets its own folder (e.g. `notes/Lectures/organic_chemistry_midterm_review/`) holding its `note.md` and `recording.wav` together — browse, back up, or move your notes directly in File Explorer/Finder, no app required. |
| **Fully Customizable** | Add your own categories, write your own prompt templates, and register any Ollama model you've pulled locally — all from an in-app Settings tab, no code edits. |
| **Optional Cloud Sync** | Point EchoPad at your OneDrive, Google Drive, iCloud, or Dropbox folder and get cross-device access, version history, and off-device backup — with no sign-in, API keys, or account access. Detected automatically. |
| **Self-Describing Notes** | Each note folder carries a small `meta.json` with its title and tags, so they survive moving the library, syncing to another computer, or deleting the index entirely. |
| **Live Transcription Progress** | Long lecture recordings show a running word count as they transcribe, instead of a static spinner with no feedback. |
| **Rename & Reorganize** | Rename a note in-app and its folder on disk follows; rename or move folders in Explorer/Finder and EchoPad picks the change up on next launch. |
| **One-Click Backup** | Zip up every note, recording, and tag from Settings — for a new laptop, a reinstall, or just peace of mind. |

Everything is indexed in a local SQLite database so search, tags, flashcards, and the dashboard stay fast as your collection grows — while the Markdown and audio files themselves remain plain files on disk, so your notes are never locked into a proprietary format.

## 📚 For Students

Open the **📚 Study** tab.

**Flashcards that actually get reviewed.** Pick any note, choose how many cards you want, and EchoPad writes question/answer pairs from your own material. Reviewing uses spaced repetition: **Again** brings a card straight back and lowers its ease, **Good** grows the gap by the card's ease factor, **Easy** pushes it further out still. So the concepts you keep fumbling keep reappearing, and the ones you know stop wasting your time. Export everything to CSV whenever you'd rather drill in Anki or Quizlet.

**Study guides across a whole course.** Select the lectures and readings for one exam and EchoPad merges them into a single revision document — grouped by *theme* rather than by which lecture something came from, with duplicate concepts merged, conflicts between notes flagged, a key-terms glossary, likely exam questions, and a "weak spots" section naming what your notes only cover thinly. It's saved as a new note, so it's searchable and exportable like anything else.

**Import the notes you already have.** Not everything starts as a recording. Use **New Note → 📄 Import a Document** for:

| Format | How it's read |
|---|---|
| `.pdf` | Text layer extracted directly. A scanned PDF is detected and you're told to import the pages as images instead. |
| `.docx` | Paragraphs and tables (older `.doc` isn't supported — re-save as `.docx`). |
| `.txt` `.md` `.csv` | Read directly, with encoding detection (UTF-8/UTF-16/cp1252). |
| `.rtf` | Text extracted from the RTF markup, including accented and unicode escapes. |
| `.png` `.jpg` `.jpeg` `.webp` `.tif` `.bmp` | OCR — for a photo of a whiteboard, a handout, or a page of a textbook. |

The extracted text runs through the same templates as a recording, and the original file is filed inside the note's folder so the note always traces back to its source. You can also attach extra material to any existing note from **📎 Attachments** in the reader view.

> OCR handles clear printed text well and struggles with handwriting, glare, and angled photos — EchoPad tells you when little text came out, and always warns you to proofread OCR results. Image OCR needs the Tesseract engine (bundled in the Docker launcher; `brew install tesseract` or `sudo apt install tesseract-ocr` otherwise).

**Templates for how students actually work:** Lecture, Reading / Chapter, Lab Report, Problem Set.

### 📅 Connecting your LMS calendar

Canvas, Blackboard, Moodle and others publish a **personal iCalendar (ICS) feed** of your assignment due dates. Subscribing to it is the officially supported way to read your deadlines elsewhere — so EchoPad needs **no password, no OAuth app, and no scraping**, and it is strictly **read-only**: EchoPad can never change anything in your LMS.

Open **📅 Deadlines → 🔗 Connect your LMS calendar**, pick your platform, and paste the feed URL. The in-app instructions tell you where to find it:

| Platform | Where the feed lives |
|---|---|
| **Canvas** | **Calendar** → **Calendar Feed** (bottom-right of the calendar sidebar) |
| **Blackboard** | **Calendar** → **Get External Calendar Link** (Ultra) or the iCalendar/Share option (Original) |
| **Moodle** | **Calendar** → **Export calendar** → **Get calendar URL** |
| **Google Calendar** | Settings → *your calendar* → **Integrate calendar** → *Secret address in iCal format* |
| **Anything else** | Any standard `.ics` feed URL, including `webcal://` links |

Once connected, EchoPad shows your deadlines grouped into **Overdue / Today / Tomorrow / This week / This month / Later**, with the course code, a link back to the assignment in your LMS, and a tick box for marking things done. Feeds refresh automatically when they're more than 6 hours old (toggleable), or on demand.

**It's your calendar — edit it freely.** Any deadline can be renamed, rescheduled, annotated, or deleted, including ones that came from your LMS. Editing an LMS deadline marks it as yours, so **the next sync keeps your version instead of overwriting it** — while still remembering what your LMS says, so **↩️ Reset to the LMS version** is one click away. Ticking something off, or editing it, also protects it from being removed if the feed later drops the entry.

#### What about Gradescope?

**Gradescope doesn't publish a personal calendar feed**, so there's nothing to subscribe to — and EchoPad deliberately won't ask for your Gradescope password to scrape the site, since that would mean storing your login and would break the moment their pages change. In practice two things cover it:

1. **Most courses run Gradescope through Canvas/Blackboard**, which mirrors the assignment into the LMS — so it's already in the feed above.
2. **Anything Gradescope-only can be added by hand** in one form (*Add a deadline by hand*), after which it behaves exactly like a synced deadline and is never touched by syncing.

> 🔐 **Treat a feed URL like a password.** Anyone holding it can read your calendar. EchoPad stores it locally on your machine and contacts nothing but your school's own server. If you ever leak one, reset it in your LMS and reconnect.

## 🧑‍💼 For Young Professionals

Open the **✅ Work** tab.

**Action items that don't get lost.** The meeting templates already write tasks as Markdown checkboxes with an owner and a due date, so EchoPad reads them straight out of your notes — no model call, no waiting, no extra step. The Work tab shows every open task across every note, grouped by meeting, with `👤 owner` and `📅 due`. Tick one off and **the note file itself is updated**, so the note stays the honest record of what's outstanding rather than drifting out of sync with a separate task list. It handles the separators models really emit (`—`, `–`, `-`, `|`), leaves unfilled template placeholders alone, and if you hand-edit a note so a line no longer matches, it says so instead of guessing.

**Follow-ups you'll actually send.** Turn a meeting, interview, or networking note into a follow-up email that opens with something specific from the conversation, confirms what you committed to, restates what they agreed to, and closes with a concrete next step. Pick the tone, edit it in place, download it. *EchoPad never sends anything* — you copy it into your own email client.

**A weekly digest for status updates.** Summarize the last 7, 14, or 30 days across every note into Highlights / Decisions Made / Open Threads / Next Focus — phrased as outcomes rather than activity. Useful for a Friday update, a standup, or building a 1:1 agenda.

**Templates for the meetings you actually sit in:** Meeting, One-on-One, Standup / Weekly Sync, Client / Discovery Call, Interview, Performance Review Prep, Networking.

## 🧭 Use Cases

- **Staying on top of a term:** Connect your LMS calendar once and every assignment due date lands in one place, alongside the notes for those courses.
- **Studying:** Record a lecture, get structured notes, generate flashcards, and merge a term's worth into one exam guide.
- **Catching up on reading:** Import a PDF chapter or photograph a handout and get it structured like everything else.
- **Meetings & projects:** Turn team syncs into tracked action items with owners, and never lose a commitment between meetings.
- **1:1s & reviews:** Keep a running record of feedback and goals, then assemble the evidence when review season arrives.
- **Interview prep & debriefs:** Record a mock interview or debrief a real one, and get strengths, gaps, and next steps.
- **Career networking:** Capture who you met and why it mattered, then draft the follow-up before the day is out.

## 🛠️ Quickstart Guide

### ✅ Easiest: One-Click Launch (Recommended)

No Python, Ollama, or FFmpeg to install by hand — everything runs in containers.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (one-time, standard installer).
2. Download this project and double-click:
   - **Windows:** [`Launch-EchoPad.bat`](Launch-EchoPad.bat)
   - **Mac:** [`Launch-EchoPad.command`](Launch-EchoPad.command) (first time, right-click → Open, to get past macOS's unsigned-app warning)
3. The first launch downloads the AI model in the background (a few minutes); every launch after that is seconds. Your browser opens automatically to EchoPad when it's ready.

To stop EchoPad later, run `docker compose down` from the project folder.

<details>
<summary><strong>Advanced: Manual setup (no Docker)</strong></summary>

#### 1. Install System Dependencies

FFmpeg decodes the audio. Tesseract is only needed if you want to import text from images — everything else works without it.

| OS | Command |
|---|---|
| macOS | `brew install ffmpeg tesseract` |
| Ubuntu/Debian | `sudo apt install ffmpeg tesseract-ocr` |
| Windows | `winget install ffmpeg` (plus [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) for image OCR) |

#### 2. Install Ollama and pull a model

EchoPad summarizes notes with a local LLM served by [Ollama](https://ollama.com/).

```bash
ollama pull llama3.2
```

Make sure Ollama is running (`ollama serve`) before you start EchoPad.

#### 3. Install Python Requirements

```bash
pip install -r requirements.txt
```

#### 4. Run EchoPad

```bash
streamlit run app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`) and start recording.

</details>

## 🐳 Configuration

| Setting | Location | Default |
|---|---|---|
| Whisper model size | Sidebar dropdown, or ⚙️ Settings → Default Models | `base` |
| Ollama model | Sidebar dropdown, or ⚙️ Settings → Default Models | `llama3.2` |
| Note storage directory | ⚙️ Settings → Storage Location, or `ECHOPAD_STORAGE_DIR` in `.env` | `./notes` |
| Note categories | Built-in list, extendable in ⚙️ Settings → Categories | Lectures, Meetings, Interviews, Networking, Brainstorming, General |
| Prompt templates | Built-in list, extendable in ⚙️ Settings → Prompt Templates | Lecture, Meeting, Interview, Networking, Brainstorming |
| App config & index | `ECHOPAD_CONFIG_DIR` | `~/.echopad` |

Copy [`.env.example`](.env.example) to `.env` for machine-level defaults that don't touch code. Everything else — storage location, categories, templates, default models, display density — lives in the in-app **⚙️ Settings** tab and persists across restarts without editing a config file.

Setting `ECHOPAD_STORAGE_DIR` *pins* the location (this is how the Docker launcher mounts your notes), and Settings will say so rather than letting the UI fight the environment.

### ⚙️ Settings tab

The Settings tab (next to Dashboard and New Note, when no note is open) is where the app becomes *yours* rather than a fixed tool:

- **📁 Categories** — add categories beyond the built-in six (e.g. "Research," "Journaling"). Custom categories can be removed once empty; built-ins are permanent so your folder structure stays predictable.
- **📝 Prompt Templates** — write your own note format. A template is just a prompt string with a `{transcript}` placeholder — copy one of the built-ins as a starting point and adjust the structure/tone to fit how *you* want notes formatted. Include `- [ ] Task — Assigned to: … — Due: …` lines and those tasks flow into the Work tab automatically.
- **🎛️ Default Models** — set which Whisper/Ollama model should be pre-selected next time you open the app, and register any Ollama model you've pulled locally that isn't in the built-in dropdown (e.g. `mistral`, `phi3`).
- **☁️ Storage Location & Cloud Sync** — keep notes on this computer only, or point them at a detected OneDrive/Google Drive/iCloud/Dropbox folder. See [the section below](#️-connecting-onedrive-google-drive-icloud-or-dropbox).
- **🎨 Display** — a compact-mode toggle for tighter spacing; theme (light/dark) is switched from Streamlit's own ⋮ menu, top-right.
- **💾 Backup & Export** — one button to zip every note, recording, and tag into a single downloadable archive.

Preferences are stored in the local index under `~/.echopad/` — nothing phones home, nothing needs an account.

### 📂 Where your notes live

```
notes/
├── Lectures/
│   ├── organic_chemistry_midterm_review/
│   │   ├── note.md                    # the generated summary + transcript
│   │   ├── recording.wav              # the original audio
│   │   └── meta.json                  # title and tags, so they travel with the note
│   └── thermodynamics_chapter_4/
│       ├── note.md
│       ├── source_chapter4.pdf        # the imported document this note came from
│       ├── whiteboard.jpg             # anything else you attached
│       └── meta.json
├── Meetings/
│   └── q3_planning_sync/
│       ├── note.md                    # its checkboxes are the action items
│       ├── recording.wav
│       └── meta.json
└── ...
```

Each note gets its own folder, named after its title, holding everything that belongs to it. Open the `notes/` folder in File Explorer or Finder any time — drag a folder to a USB drive to back it up, rename it, or move it between categories, and EchoPad will pick up the change next time it starts. Deleting a note from within the app removes its whole folder; deleting it here is exactly the same as using the app's Delete button.

The search index is **not** stored with your notes — it lives in `~/.echopad/` on each machine and rebuilds itself from the files above, because cloud-sync clients can lock or partially upload a live database file. Since every note carries its own `meta.json`, a rebuilt index recovers titles and tags too; it's safe to delete the index at any time. Action items are re-derived from each note's checkboxes on every launch, so they're never stale either.

Flashcard review history is the one thing that lives only in the index, since it isn't derivable from the notes. It's included in the Settings → Backup zip, and a note that briefly goes missing (a cloud folder mid-sync) will *not* discard its cards — only deleting a note from within the app does that.

### ☁️ Connecting OneDrive, Google Drive, iCloud, or Dropbox

Because EchoPad stores plain files, "connecting" a cloud service just means pointing the notes folder at the folder that provider's own desktop app already syncs. **No OAuth, no API keys, no account access** — and you get cross-device access, version history, and off-device backup from a client you already trust.

1. Make sure the provider's desktop sync app is installed and signed in (OneDrive, [Google Drive for Desktop](https://www.google.com/drive/download/), iCloud Drive, or Dropbox).
2. Open **⚙️ Settings → ☁️ Storage Location & Cloud Sync**. Detected providers are listed automatically.
3. Pick one and choose **Use This Location**. You'll be asked whether to move your existing notes across.
4. Repeat on your other computer, pointing it at the same synced folder — your notes appear there, tags included.

**How the move is kept safe:** every file is copied and size-verified *before* anything is deleted. If any copy fails, the copies are rolled back and your current folder is left exactly as it was. Files already present at the destination are reported and skipped rather than overwritten.

> **The honest privacy tradeoff:** notes in a synced folder **do** leave your machine and reach that provider, so the "nothing leaves your computer" guarantee narrows to *the transcription and summarization stay local* — no note text is ever sent to an AI service either way. If you want the fully-private setup, keep the default local folder. EchoPad always uses a dedicated `EchoPad` subfolder inside the sync root, never the root itself, so it never touches unrelated files.

EchoPad keeps a separate index per notes location, so switching between a local folder and a cloud folder doesn't mix the two libraries together.

## 🧪 Running Tests

```bash
pytest
```

The suite covers the note index, storage relocation (including rollback when a copy fails), cloud-folder detection, sidecar metadata recovery, document export, document import (PDF/DOCX/text fixtures are generated on the fly), action-item parsing and write-back, flashcard parsing, the spaced-repetition scheduling math, ICS feed parsing (all-day/TZID/folded lines/VTODO/recurrence/malformed input), feed-URL scheme validation, and the rules that keep a synced deadline from clobbering your own edits. It needs no Ollama, no Whisper model, and **no network** — HTTP fetching is exercised against stubs.

CI runs the same command on Python 3.11 and 3.12 — see [`.github/workflows/ci.yml`](.github/workflows/ci.yml). `pythonpath = ["."]` in `pyproject.toml` is what lets a bare `pytest` import the top-level modules; without it, only `python -m pytest` works.

## 🩹 Troubleshooting

- **"Docker Desktop was not found"** (one-click launch) — install it from [docker.com](https://www.docker.com/products/docker-desktop/), make sure it's actually running (check for the whale icon), then double-click the launcher again.
- **First launch seems stuck / browser never opens** — the first run downloads the LLM (~2GB) and Whisper model; this can take a few minutes on a slow connection. Check progress with `docker compose logs -f`.
- **"Ollama is not running"** (manual setup only) — start it with `ollama serve` in a separate terminal, then refresh the page.
- **First transcription is slow** — the Whisper model downloads on first use; subsequent runs are much faster.
- **No audio recorded** — check your browser has granted microphone permission for the EchoPad tab.
- **Notes from another computer aren't showing up** — let the sync client finish downloading them (OneDrive/Drive show a progress icon), then restart EchoPad; it indexes new files on launch.
- **A note's title or tags look wrong after a move** — EchoPad rebuilds those from each note's `meta.json`. Notes created before that file existed fall back to their folder name; re-saving tags on such a note writes the sidecar and fixes it for good.
- **Search or tags seem out of date** — quit EchoPad, delete `~/.echopad/index-*.db`, and restart. The index rebuilds from your notes (flashcard review history is the only thing that doesn't survive, so back it up from Settings first if it matters).
- **An action item isn't showing up** — it has to be a Markdown checkbox (`- [ ] Task`). Lines still holding an unfilled template placeholder like `- [ ] **[Task 1]**` are ignored on purpose. Hit **Rescan** in the Work tab after editing notes outside the app mid-session.
- **"That line has changed in the note"** — the note was hand-edited since it was scanned, so EchoPad won't guess which line to tick. Hit **Rescan** and try again.
- **Flashcard generation returns nothing** — the model didn't follow the `Q:` / `A:` format. Try again, or switch to a larger Ollama model in the sidebar; small models are less reliable at holding a strict output shape.
- **An imported PDF comes out empty** — it's a scan with no text layer. Export the pages as images and import those so OCR runs on them.
- **Image import says Tesseract isn't installed** — install the OCR engine itself (`brew install tesseract` / `sudo apt install tesseract-ocr`); the Python package alone isn't enough. The Docker launcher includes it.
- **"That URL didn't return a calendar"** — you've most likely copied the link to the calendar *web page* rather than the feed. Look for the button that gives you an `.ics` or `webcal://` link.
- **A feed that used to work now says the server refused it (401/403)** — LMS feed URLs are revoked when you reset them. Generate a fresh one and paste it in again.
- **A deadline in my LMS isn't showing** — feeds only publish items with a date, and EchoPad looks a year ahead. Hit **Sync** on the feed; if it's still missing, it may not be in the calendar at all (common for Gradescope-only work) — add it by hand.
- **A deadline I edited went back to the LMS wording** — that happens only if you used **↩️ Reset to the LMS version**. Ordinary syncing leaves edited deadlines alone.
- **Recurring class events look wrong** — EchoPad expands the common weekly/daily/monthly patterns. Anything more exotic falls back to showing a single occurrence rather than guessing.

## 📄 License

MIT
