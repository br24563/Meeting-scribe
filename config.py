import os
from pathlib import Path

# Local storage path for saved Markdown notes
STORAGE_DIR = Path("./notes")
STORAGE_DIR.mkdir(exist_ok=True)

# Selectable Whisper Models (Speed vs Accuracy)
WHISPER_MODELS = ["tiny", "base", "small"]
DEFAULT_WHISPER_MODEL = "base"

# Selectable Ollama Models
OLLAMA_MODELS = ["llama3.2", "qwen2.5", "deepseek-r1:1.5b"]
DEFAULT_OLLAMA_MODEL = "llama3.2"

# Default subsections for note categorization
SUBSECTIONS = ["General", "Lectures", "Meetings", "Brainstorming"]

# Notion-style Structured Markdown Prompt
NOTION_PROMPT = """
You are an expert executive note-taker. Format the transcript below into a clean, modern Notion-style Markdown document.

Follow this exact visual layout:

> 💡 **TL;DR / Quick Summary**
> (Write a 2-3 sentence high-level executive summary of the entire session.)

---

### 🧠 Detailed Notes

#### 1. Core Discussion & Topics
* **[Topic/Concept 1]:** Detailed explanation of key points discussed, arguments made, or technical details shared.
* **[Topic/Concept 2]:** Additional deep-dive details.

#### 2. Key Decisions & Takeaways
* **Decision:** Explicit decision made during the session.
* **Key Insight:** Important takeaway or realization.

---

### 📋 Action Items
- [ ] **[Task 1]** — Assigned to: [Name/Role or "Unassigned"]
- [ ] **[Task 2]** — Assigned to: [Name/Role or "Unassigned"]

---
Transcript:
{transcript}
"""
