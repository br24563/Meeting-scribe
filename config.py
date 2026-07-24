import os
from pathlib import Path

STORAGE_DIR = Path("./notes")
STORAGE_DIR.mkdir(exist_ok=True)

WHISPER_MODELS = ["tiny", "base", "small"]
DEFAULT_WHISPER_MODEL = "base"

OLLAMA_MODELS = ["llama3.2", "qwen2.5", "deepseek-r1:1.5b"]
DEFAULT_OLLAMA_MODEL = "llama3.2"

SUBSECTIONS = ["General", "Lectures", "Meetings", "Brainstorming", "Interviews"]

TEMPLATES = {
    "Meeting": """
You are an executive note-taker. Format the transcript into a Notion-style meeting document.

> 💡 **TL;DR / Quick Summary**
> (Write a 2-3 sentence executive summary)

---
### 🧠 Detailed Notes
#### 1. Key Discussion Points
* **[Topic 1]:** Detailed discussion items.
#### 2. Decisions Made
* **Decision:** Key decisions reached.

---
### 📋 Action Items
- [ ] **[Task 1]** — Assigned to: [Name/Role]

---
### 🏷️ Relevant Tags
#meeting #[topic_hashtag] #[project_hashtag]

Transcript:
{transcript}
""",
    "Lecture": """
You are an academic note-taker. Format the transcript into clean study notes.

> 💡 **Core Thesis / Main Concept**
> (Write a 2-3 sentence summary of the lecture focus)

---
### 📖 Key Concepts & Definitions
* **[Term/Concept 1]:** Definition and explanation.
* **[Term/Concept 2]:** Definition and explanation.

---
### 🔬 Detailed Breakdown
#### 1. Topic Overview
* Explanation of major arguments, equations, or historical events discussed.

---
### 🏷️ Relevant Tags
#lecture #[subject_hashtag] #[study_hashtag]

Transcript:
{transcript}
""",
    "Brainstorming": """
You are an innovation assistant. Format the transcript into structured ideation notes.

> 💡 **Core Vision**
> (2-3 sentence high-level vision summary)

---
### 💡 Ideas Generated
* **[Idea 1]:** Key concept, pros, and potential blockers.
* **[Idea 2]:** Key concept, pros, and potential blockers.

---
### 🚀 Next Experiments / Explorations
- [ ] Explore feasibility of [Idea]

---
### 🏷️ Relevant Tags
#brainstorm #ideas #[topic_hashtag]

Transcript:
{transcript}
""",
    "Interview": """
You are a hiring/user-research assistant. Format the transcript into clean interview notes.

> 💡 **Executive Evaluation Summary**
> (2-3 sentence candidate/user summary)

---
### 💬 Highlights & Key Quotes
* **[Topic/Question]:** "Direct quote or core sentiment."

---
### 📊 Key Insights & Red/Green Flags
* **Positive Signals:** [Key strengths]
* **Areas of Concern:** [Potential risks]

---
### 🏷️ Relevant Tags
#interview #research #[role_or_user_hashtag]

Transcript:
{transcript}
"""
}
