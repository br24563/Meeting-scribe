# 🎙️ EchoPad — Local AI Voice Notebook

EchoPad is a zero-cost, private, local-first meeting and lecture assistant. It records audio directly from your browser, transcribes speech locally using `faster-whisper`, and generates structured Notion-style Markdown summaries using local LLMs via `Ollama`.

## 🚀 Features
* **100% Free & Offline:** Zero third-party API keys or subscription fees required.
* **Notion-Style Summaries:** Auto-generates TL;DR summaries, key takeaways, and action items.
* **Subsection Categorization:** Organize recordings by Meetings, Lectures, or Ideas.
* **Local Markdown Notebook:** Automatically stores notes as standard `.md` files on your device.

## 🛠️ Quickstart Guide

1. **Install System Dependencies (FFmpeg):**
   * macOS: `brew install ffmpeg`
   * Ubuntu/Debian: `sudo apt install ffmpeg`

2. **Install Python Requirements:**
   ```bash
   pip install -r requirements.txt
