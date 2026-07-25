import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Machine-level app config (chosen notes location, the search index). Kept
# separate from the notes themselves so the notes folder stays portable — and
# so it can live somewhere cloud-synced without dragging a live SQLite file
# along with it. See db.index_path() and the README's storage section.
APP_CONFIG_DIR = Path(os.environ.get("ECHOPAD_CONFIG_DIR", Path.home() / ".echopad")).expanduser()
LOCATION_FILE = APP_CONFIG_DIR / "location.json"
DEFAULT_STORAGE_DIR = Path("./notes")


def storage_dir_is_pinned() -> bool:
    """True when the notes location is fixed by the environment (Docker, or an
    explicit .env), in which case the UI shouldn't offer to move it."""
    return bool(os.environ.get("ECHOPAD_STORAGE_DIR"))


def _saved_storage_dir():
    try:
        saved = json.loads(LOCATION_FILE.read_text(encoding="utf-8")).get("storage_dir")
    except (OSError, ValueError):
        return None
    return Path(saved).expanduser() if saved else None


def resolve_storage_dir() -> Path:
    """Precedence: environment > location saved from the Settings tab > default."""
    from_env = os.environ.get("ECHOPAD_STORAGE_DIR")
    if from_env:
        return Path(from_env).expanduser()
    return _saved_storage_dir() or DEFAULT_STORAGE_DIR


def set_storage_dir(new_dir) -> Path:
    """Persist a new notes location and update STORAGE_DIR in place, so the
    running app picks it up on its next rerun without a restart."""
    global STORAGE_DIR
    new_dir = Path(new_dir).expanduser()
    new_dir.mkdir(parents=True, exist_ok=True)
    APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOCATION_FILE.write_text(json.dumps({"storage_dir": str(new_dir)}, indent=2), encoding="utf-8")
    STORAGE_DIR = new_dir
    return new_dir


APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR = resolve_storage_dir()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

WHISPER_MODELS = ["tiny", "base", "small"]
DEFAULT_WHISPER_MODEL = os.environ.get("ECHOPAD_WHISPER_MODEL", "base")

OLLAMA_MODELS = ["llama3.2", "qwen2.5", "deepseek-r1:1.5b"]
DEFAULT_OLLAMA_MODEL = os.environ.get("ECHOPAD_OLLAMA_MODEL", "llama3.2")

SUBSECTIONS = ["Lectures", "Meetings", "Interviews", "Networking", "Brainstorming", "General"]

TEMPLATES = {
    "Lecture": """
You are an academic note-taker helping a student study effectively. Format the transcript into clean, exam-ready study notes.

> 💡 **Core Thesis / Main Concept**
> (2-3 sentence summary of what this lecture was really about)

---
### 📖 Key Concepts & Definitions
* **[Term/Concept 1]:** Clear, exam-ready definition and explanation.
* **[Term/Concept 2]:** Clear, exam-ready definition and explanation.

---
### 🔬 Detailed Breakdown
#### 1. Topic Overview
* Explanation of major arguments, equations, or historical events discussed, in the order presented.

---
### ✅ Self-Check Questions
* [Question testing understanding of a key concept]
* [Question testing understanding of a key concept]

---
### 🌟 Exam-Relevant Highlights
* [Anything the lecturer flagged as important, likely to be tested, or repeated for emphasis]

---
### 🏷️ Relevant Tags
#lecture #[subject_hashtag] #[study_hashtag]

Transcript:
{transcript}
""",
    "Meeting": """
You are an executive note-taker. Format the transcript into a Notion-style meeting document suitable for sharing with a team or professor.

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
- [ ] **[Task 1]** — Assigned to: [Name/Role] — Due: [Date if mentioned]

---
### 📅 Follow-Ups
* [Anything requiring a future meeting, email, or check-in]

---
### 🏷️ Relevant Tags
#meeting #[topic_hashtag] #[project_hashtag]

Transcript:
{transcript}
""",
    "Interview": """
You are a career-coaching assistant helping a student or early-career professional get more out of a job interview — whether it was a live interview or a practice run.

> 💡 **Executive Evaluation Summary**
> (2-3 sentence summary of how the interview went and overall readiness)

---
### 🏢 Role & Context
* **Role/Company (if mentioned):** [Role, Company]
* **Interview Stage:** [e.g. phone screen, technical, behavioral, final round, mock practice]

---
### 💬 Highlights & Key Quotes
* **[Question Asked]:** "Direct quote or core sentiment of the answer given."

---
### 📊 Strengths Demonstrated
* [Specific moments where the answer was strong, well-structured, or compelling]

---
### 🚩 Areas to Improve
* [Answers that were vague, too long, missing structure (e.g. STAR method), or off-topic]

---
### 🎯 Next Steps
- [ ] [e.g. Send a thank-you note within 24 hours]
- [ ] [e.g. Practice a tighter answer for "Tell me about yourself"]

---
### 🏷️ Relevant Tags
#interview #careerprep #[role_or_company_hashtag]

Transcript:
{transcript}
""",
    "Networking": """
You are a career-networking assistant helping a student or young professional follow up effectively after a networking conversation, informational interview, or career fair chat.

> 💡 **Quick Summary**
> (2-3 sentence summary of who this person is and why the conversation mattered)

---
### 🤝 Contact Details
* **Name:** [Name]
* **Role / Company:** [Role, Company]
* **How We Met:** [Career fair, LinkedIn intro, event name, etc.]

---
### 💬 Key Takeaways
* [Advice, insight, or opinion they shared worth remembering]

---
### 🔗 Shared Interests / Common Ground
* [Anything personal or professional to reference in a follow-up message]

---
### 📬 Follow-Up Actions
- [ ] Send a connection request / thank-you message within 48 hours
- [ ] [Any specific ask they made, or offer they extended]

---
### 🏷️ Relevant Tags
#networking #careerconnections #[industry_hashtag]

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
"""
}
