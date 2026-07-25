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
""",
    # ------------------------- Study templates -------------------------
    "Reading / Chapter": """
You are a study partner helping a student get the most out of assigned reading. The transcript is the student reading aloud, summarizing, or discussing a text.

> 💡 **What This Reading Is Arguing**
> (2-3 sentence summary of the central claim or purpose)

---
### 📚 Source
* **Text / Chapter:** [Title, chapter, or pages if mentioned]
* **Author's Position:** [Where this author stands, in one line]

---
### 🔑 Key Terms & Definitions
* **[Term]:** Exam-ready definition in the student's own words.

---
### 🧩 Main Arguments & Evidence
#### 1. [Argument]
* The claim, the evidence given for it, and any stated limitation.

---
### 🤔 Critiques & Open Questions
* [Where the argument is weak, contested, or unclear — good discussion-section material]

---
### 🔗 Connections to Course Material
* [How this links to lectures or other readings mentioned]

---
### ✅ Self-Check Questions
* [Question testing comprehension of a main argument]

---
### 🏷️ Relevant Tags
#reading #[subject_hashtag] #[topic_hashtag]

Transcript:
{transcript}
""",
    "Lab Report": """
You are a lab partner turning a spoken account of an experiment into structured lab notes a student can write up later.

> 💡 **Purpose & Outcome**
> (2-3 sentences: what was tested and what happened)

---
### 🎯 Hypothesis & Variables
* **Hypothesis:** [As stated or implied]
* **Independent / Dependent Variables:** [What was changed, what was measured]
* **Controls:** [What was held constant]

---
### 🔬 Procedure as Performed
1. [Step actually carried out, including any deviation from the protocol]

---
### 📊 Observations & Data
* [Measurements, readings, and qualitative observations mentioned]

---
### 🧠 Analysis & Interpretation
* [What the data suggests, and whether it supports the hypothesis]

---
### ⚠️ Sources of Error
* [Anything noted as imprecise, contaminated, mis-measured, or uncontrolled]

---
### 📋 Follow-Up Before Write-Up
- [ ] **[Task]** — Assigned to: [Name/Self] — Due: [Date if mentioned]

---
### 🏷️ Relevant Tags
#lab #[course_hashtag] #[experiment_hashtag]

Transcript:
{transcript}
""",
    "Problem Set": """
You are a tutor turning a student's spoken work through problems into a reviewable worked-solutions document.

> 💡 **Concepts This Set Is Testing**
> (2-3 sentences naming the underlying skills)

---
### ✏️ Worked Problems
#### Problem [N]
* **Asked:** [What the problem wants]
* **Approach:** [Method chosen and why]
* **Steps:** [Key steps, equations, or reasoning in order]
* **Answer:** [Final result, with units]

---
### ⚠️ Mistakes & Corrections
* [Wrong turns taken and what fixed them — the most valuable part to review]

---
### 🧠 Patterns to Remember
* [Reusable technique or shortcut worth carrying into the exam]

---
### ❓ Still Unclear — Ask About These
- [ ] **[Question to bring to office hours]** — Assigned to: Self — Due: [Date if mentioned]

---
### 🏷️ Relevant Tags
#problemset #[course_hashtag] #[topic_hashtag]

Transcript:
{transcript}
""",
    # --------------------- Professional templates ----------------------
    "One-on-One": """
You are an executive assistant documenting a 1:1 between an employee and their manager, in a way that is useful to revisit before the next one.

> 💡 **TL;DR**
> (2-3 sentence summary of the conversation and its tone)

---
### 🗣️ Topics Discussed
* **[Topic]:** What was raised and the response.

---
### 📈 Feedback Received
* **Strengths noted:** [Specific praise, with the example given]
* **Areas to develop:** [Specific critique, with the example given]

---
### 🎯 Goals & Expectations
* [Any goal, metric, or expectation set or restated, with its timeframe]

---
### 🚧 Blockers & Support Requested
* [What the employee said they need, and what was promised]

---
### 📋 Action Items
- [ ] **[Task]** — Assigned to: [Name/Role] — Due: [Date if mentioned]

---
### 💬 Raise Next Time
* [Anything deferred, or worth following up on in the next 1:1]

---
### 🏷️ Relevant Tags
#oneonone #career #[manager_or_team_hashtag]

Transcript:
{transcript}
""",
    "Standup / Weekly Sync": """
You are a team lead's note-taker capturing a standup or weekly sync so absent teammates can catch up in under a minute.

> 💡 **Status in One Line**
> (Is the team on track? Anything at risk?)

---
### ✅ Progress Since Last Sync
* **[Person/Workstream]:** What shipped or moved.

---
### 🎯 Plan Until Next Sync
* **[Person/Workstream]:** What they committed to next.

---
### 🚧 Blockers & Risks
* **[Blocker]:** Who is blocked, on what, and who can unblock it.

---
### 🧭 Decisions Made
* [Any decision reached, so nobody relitigates it later]

---
### 📋 Action Items
- [ ] **[Task]** — Assigned to: [Name/Role] — Due: [Date if mentioned]

---
### 🏷️ Relevant Tags
#standup #[team_hashtag] #[project_hashtag]

Transcript:
{transcript}
""",
    "Client / Discovery Call": """
You are a client-facing note-taker turning a discovery or client call into notes that survive a handoff to a colleague.

> 💡 **Deal / Relationship Summary**
> (2-3 sentences: who they are, what they need, where this stands)

---
### 🏢 Client Context
* **Organization & Contacts:** [Company, names, roles present]
* **Their Current Setup:** [Tools, process, or vendor they use today]

---
### 🎯 Needs & Pain Points
* **[Need]:** In their words where possible, plus why it matters to them.

---
### 💬 Notable Quotes
* "[Direct quote worth repeating internally or in a proposal]"

---
### ⚠️ Objections & Concerns
* **[Objection]:** What was raised, and how it was answered.

---
### 💰 Scope, Budget & Timeline Signals
* [Anything said about size, budget, authority, or deadlines]

---
### 📋 Action Items
- [ ] **[Task]** — Assigned to: [Name/Role] — Due: [Date if mentioned]

---
### 📅 Agreed Next Step
* [The specific next meeting, deliverable, or decision, and when]

---
### 🏷️ Relevant Tags
#client #[company_hashtag] #[stage_hashtag]

Transcript:
{transcript}
""",
    "Performance Review Prep": """
You are a career coach helping someone assemble evidence for a performance review or promotion case from a spoken brain-dump.

> 💡 **The Case in Three Sentences**
> (The strongest version of this person's impact this cycle)

---
### 🏆 Accomplishments With Evidence
* **[Accomplishment]:** What was done, the measurable outcome, and who benefited. Flag any claim that still needs a number.

---
### 🤝 Collaboration & Influence
* [Mentoring, cross-team work, or decisions influenced beyond their own scope]

---
### 📈 Growth Since Last Review
* [Skills built, feedback acted on, and how that showed up in the work]

---
### 🎯 Goals for Next Cycle
* [Concrete, checkable goals to propose]

---
### 🚩 Gaps to Address Honestly
* [Weakness worth naming first, with the plan for it]

---
### 📋 Prep Action Items
- [ ] **[Task, e.g. pull metrics for project X]** — Assigned to: Self — Due: [Date if mentioned]

---
### 🏷️ Relevant Tags
#performancereview #career #[role_hashtag]

Transcript:
{transcript}
"""
}

# Which templates belong to which audience — used only to group the picker.
STUDY_TEMPLATES = ("Lecture", "Reading / Chapter", "Lab Report", "Problem Set")
WORK_TEMPLATES = (
    "Meeting", "One-on-One", "Standup / Weekly Sync", "Client / Discovery Call",
    "Interview", "Performance Review Prep", "Networking",
)

# ---------------------------------------------------------------------------
# Prompts for things derived from notes you've already saved, rather than
# from a fresh recording.
# ---------------------------------------------------------------------------

FLASHCARD_PROMPT = """You are creating study flashcards from a student's notes.

Write {count} flashcards covering the most testable facts, definitions, and relationships in the notes below.

Rules:
- Output NOTHING but the cards, in exactly this format:
Q: <one specific question>
A: <a concise answer, 1-2 sentences>
- One blank line between cards.
- Each question must stand alone — never say "according to the notes" or "this lecture".
- Prefer specifics (definitions, mechanisms, dates, formulas, cause-and-effect) over vague prompts.
- Do not number the cards. Do not add commentary, headings, or a preamble.

Notes:
{note}
"""

FOLLOWUP_PROMPT = """You are drafting a follow-up message on behalf of the person whose notes appear below.

Write a {tone} follow-up email that:
- Opens by referencing something specific and genuine from the conversation (not a generic pleasantry).
- Confirms any commitments *they* made, and politely restates what the other side agreed to.
- Asks about any open question left unresolved.
- Closes with a clear, low-friction next step.

Keep it under 200 words. Output a "Subject:" line, then the body. No placeholders like [Name] unless the notes genuinely don't say — if a name is missing, use a neutral greeting instead.

Notes:
{note}
"""

STUDY_GUIDE_PROMPT = """You are building one consolidated exam study guide from several of a student's notes.

Merge them into a single revision document:
- Open with a short "Big Picture" section tying the material together.
- Group by theme, NOT by which note something came from.
- Merge duplicate concepts into one entry; where notes conflict, flag the conflict.
- Include a "Key Terms" glossary, a "Likely Exam Questions" section, and a "Weak Spots to Review" section listing what the notes cover only thinly.
- Use Markdown headings. Do not invent material that isn't in the notes.

Notes to merge:
{note}
"""

DIGEST_PROMPT = """You are writing a concise status update from someone's own notes for the period below.

Produce:
- **Highlights** — what actually progressed, phrased as outcomes rather than activity.
- **Decisions Made** — anything settled, with who settled it.
- **Open Threads** — what's unresolved and waiting on whom.
- **Next Period's Focus** — what the notes imply comes next.

Be specific and brief; this is meant to be pasted into a weekly update. Attribute nothing that isn't in the notes.

Notes for this period:
{note}
"""
