# 🎙️ EchoPad — The Private AI Notebook for Students & Young Professionals

[![CI](https://github.com/br24563/Echo-pad/actions/workflows/ci.yml/badge.svg)](https://github.com/br24563/Echo-pad/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Local-first](https://img.shields.io/badge/data-100%25%20local-brightgreen)
![Version](https://img.shields.io/badge/version-0.3.0-orange)

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
| **Purpose-Built Templates** | Distinct note formats for Lectures, Meetings, Interviews, Brainstorming, and Networking — each tuned to what that context actually needs. |
| **Live Mic or File Upload** | Record directly from your browser, or upload an existing `.mp3`, `.m4a`, or `.wav`. |
| **Full-Text Search** | Instantly find any past note by keyword — great for exam review or recalling "who was that contact from the career fair?" |
| **Tags & Dashboard** | Tag notes (e.g. `midterm`, `chapter-4`), browse by tag, and see a home dashboard with note counts per category and your most recently added notes. |
| **In-App Editing** | Refine AI-generated notes without leaving the app. |
| **Multi-Format Export** | Download any note as Markdown, HTML, or PDF for sharing or printing. |
| **Delete, With a Safety Net** | Every note has a Delete button that opens a confirmation dialog first — no accidental one-click data loss. |
| **Explorer-Friendly Storage** | Every note gets its own folder (e.g. `notes/Lectures/organic_chemistry_midterm_review/`) holding its `note.md` and `recording.wav` together — browse, back up, or move your notes directly in File Explorer/Finder, no app required. |
| **Fully Customizable** | Add your own categories, write your own prompt templates, and register any Ollama model you've pulled locally — all from an in-app Settings tab, no code edits. |
| **Live Transcription Progress** | Long lecture recordings show a running word count as they transcribe, instead of a static spinner with no feedback. |
| **One-Click Backup** | Zip up every note, recording, and tag from Settings — for a new laptop, a reinstall, or just peace of mind. |

Everything is indexed in a local SQLite database (`notes/echopad.db`) so search, tags, and the dashboard stay fast as your note collection grows — while the Markdown and audio files themselves remain plain files on disk, so your notes are never locked into a proprietary format.

## 🧭 Use Cases

- **Studying:** Record a lecture, get structured notes with definitions and self-check questions for exam prep.
- **Interview Prep & Debriefs:** Record a mock interview or debrief a real one, and get an evaluation summary with strengths, red flags, and next steps.
- **Career Networking:** Capture notes right after a networking event or informational interview so no contact or follow-up falls through the cracks.
- **Group Projects & Meetings:** Turn team syncs into action items with clear owners.

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

#### 1. Install System Dependencies (FFmpeg)

| OS | Command |
|---|---|
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| Windows | `winget install ffmpeg` (or download from [ffmpeg.org](https://ffmpeg.org/download.html)) |

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
| Note storage directory | `ECHOPAD_STORAGE_DIR` in `.env` | `./notes` |
| Note categories | Built-in list, extendable in ⚙️ Settings → Categories | Lectures, Meetings, Interviews, Networking, Brainstorming, General |
| Prompt templates | Built-in list, extendable in ⚙️ Settings → Prompt Templates | Lecture, Meeting, Interview, Networking, Brainstorming |

Copy [`.env.example`](.env.example) to `.env` for machine-level defaults (storage location, etc.) that don't touch code. Everything else — categories, templates, default models, display density — lives in the in-app **⚙️ Settings** tab and is saved locally, so it persists across restarts without editing a config file.

### ⚙️ Settings tab

The Settings tab (next to Dashboard and New Note, when no note is open) is where the app becomes *yours* rather than a fixed tool:

- **📁 Categories** — add categories beyond the built-in six (e.g. "Research," "Journaling"). Custom categories can be removed once empty; built-ins are permanent so your folder structure stays predictable.
- **📝 Prompt Templates** — write your own note format. A template is just a prompt string with a `{transcript}` placeholder — copy one of the built-ins as a starting point and adjust the structure/tone to fit how *you* want notes formatted.
- **🎛️ Default Models** — set which Whisper/Ollama model should be pre-selected next time you open the app, and register any Ollama model you've pulled locally that isn't in the built-in dropdown (e.g. `mistral`, `phi3`).
- **🎨 Display** — a compact-mode toggle for tighter spacing; theme (light/dark) is switched from Streamlit's own ⋮ menu, top-right.
- **💾 Backup & Export** — one button to zip every note, recording, and tag into a single downloadable archive.

All of it is stored in the same local SQLite index as your notes (`notes/echopad.db`) — nothing phones home, nothing needs an account.

### 📂 Where your notes live

```
notes/
├── echopad.db                                   # search index (safe to delete — rebuilds automatically)
├── Lectures/
│   └── organic_chemistry_midterm_review/
│       ├── note.md                              # the generated summary + transcript
│       └── recording.wav                        # the original audio
├── Interviews/
│   └── acme_corp_debrief/
│       ├── note.md
│       └── recording.wav
└── ...
```

Each note gets its own folder, named after its title, holding everything that belongs to it. Open the `notes/` folder in File Explorer or Finder any time — drag a folder to a USB drive to back it up, rename it, or move it between categories, and EchoPad will pick up the change next time it starts (it re-scans anything not yet in its index). Deleting a note from within the app removes its whole folder; deleting it here is exactly the same as using the app's Delete button.

## 🧪 Running Tests

```bash
pytest
```

## 🩹 Troubleshooting

- **"Docker Desktop was not found"** (one-click launch) — install it from [docker.com](https://www.docker.com/products/docker-desktop/), make sure it's actually running (check for the whale icon), then double-click the launcher again.
- **First launch seems stuck / browser never opens** — the first run downloads the LLM (~2GB) and Whisper model; this can take a few minutes on a slow connection. Check progress with `docker compose logs -f`.
- **"Ollama is not running"** (manual setup only) — start it with `ollama serve` in a separate terminal, then refresh the page.
- **First transcription is slow** — the Whisper model downloads on first use; subsequent runs are much faster.
- **No audio recorded** — check your browser has granted microphone permission for the EchoPad tab.

## 📄 License

MIT
