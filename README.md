# 🎙️ EchoPad — The Private AI Notebook for Students & Young Professionals

[![CI](https://github.com/br24563/Echo-pad/actions/workflows/ci.yml/badge.svg)](https://github.com/br24563/Echo-pad/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Local-first](https://img.shields.io/badge/data-100%25%20local-brightgreen)

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
| **In-App Editing** | Refine AI-generated notes without leaving the app. |
| **Multi-Format Export** | Download any note as Markdown, HTML, or PDF for sharing or printing. |

## 🧭 Use Cases

- **Studying:** Record a lecture, get structured notes with definitions and self-check questions for exam prep.
- **Interview Prep & Debriefs:** Record a mock interview or debrief a real one, and get an evaluation summary with strengths, red flags, and next steps.
- **Career Networking:** Capture notes right after a networking event or informational interview so no contact or follow-up falls through the cracks.
- **Group Projects & Meetings:** Turn team syncs into action items with clear owners.

## 🛠️ Quickstart Guide

### 1. Install System Dependencies (FFmpeg)

| OS | Command |
|---|---|
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| Windows | `winget install ffmpeg` (or download from [ffmpeg.org](https://ffmpeg.org/download.html)) |

### 2. Install Ollama and pull a model

EchoPad summarizes notes with a local LLM served by [Ollama](https://ollama.com/).

```bash
ollama pull llama3.2
```

Make sure Ollama is running (`ollama serve`) before you start EchoPad.

### 3. Install Python Requirements

```bash
pip install -r requirements.txt
```

### 4. Run EchoPad

```bash
streamlit run app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`) and start recording.

### Optional: Run with Docker

```bash
docker compose up --build
```

## 🐳 Configuration

| Setting | Location | Default |
|---|---|---|
| Whisper model size | Sidebar dropdown | `base` |
| Ollama model | Sidebar dropdown | `llama3.2` |
| Note storage directory | `config.py` → `STORAGE_DIR` | `./notes` |
| Note categories | `config.py` → `SUBSECTIONS` | Lectures, Meetings, Interviews, Networking, Brainstorming, General |

Notes are saved as plain `.md` files under `./notes/<category>/`, alongside the original audio, so your data stays portable and yours.

## 🧪 Running Tests

```bash
pytest
```

## 🩹 Troubleshooting

- **"Ollama is not running"** — start it with `ollama serve` in a separate terminal, then refresh the page.
- **First transcription is slow** — the Whisper model downloads on first use; subsequent runs are much faster.
- **No audio recorded** — check your browser has granted microphone permission for the EchoPad tab.

## 📄 License

MIT
