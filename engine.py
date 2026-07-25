import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
import ollama
from faster_whisper import WhisperModel
import markdown
from fpdf import FPDF
import config

def check_ollama_status() -> bool:
    """Verify if local Ollama engine is active."""
    try:
        ollama.list()
        return True
    except Exception:
        return False

@lru_cache(maxsize=None)
def _load_whisper_model(model_size: str) -> WhisperModel:
    """Load (and cache) a Whisper model so repeated transcriptions don't reload it from disk."""
    return WhisperModel(model_size, device="cpu", compute_type="int8")

def transcribe_audio(audio_bytes, model_size: str = config.DEFAULT_WHISPER_MODEL, translate: bool = False,
                      on_progress=None) -> str:
    """Transcribe or translate audio locally using faster-whisper.

    If given, `on_progress(transcript_so_far, segment)` is called after each
    segment is decoded, so a caller (e.g. the UI) can show live progress
    instead of a static spinner during long recordings.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes.read() if hasattr(audio_bytes, "read") else audio_bytes)
        temp_path = tmp.name

    try:
        model = _load_whisper_model(model_size)
        task = "translate" if translate else "transcribe"
        segments, _ = model.transcribe(temp_path, beam_size=5, task=task)
        parts = []
        for segment in segments:
            parts.append(segment.text.strip())
            if on_progress:
                on_progress(" ".join(parts), segment)
        full_transcript = " ".join(parts)
    finally:
        os.remove(temp_path)

    return full_transcript

def generate_summary(transcript: str, template: str, model_name: str = config.DEFAULT_OLLAMA_MODEL) -> str:
    """Generate a structured summary from `transcript` using Ollama.

    `template` is the full prompt template string (must contain a
    `{transcript}` placeholder) — callers resolve which template to use
    (built-in or user-defined) before calling this.
    """
    prompt = template.format(transcript=transcript)
    response = ollama.generate(model=model_name, prompt=prompt)
    return response["response"]

# ---------------------------------------------------------------------------
# Action items
#
# The note templates already emit tasks as Markdown checkboxes, e.g.
#   - [ ] **Send the deck** — Assigned to: Priya — Due: Friday
# so these are parsed straight out of the note text. No model call, no waiting,
# and the note file stays the single source of truth for what's outstanding.
# ---------------------------------------------------------------------------

_CHECKBOX_RE = re.compile(r"^(\s*)([-*+])\s+\[([ xX])\]\s*(.+?)\s*$")
_PLACEHOLDER_RE = re.compile(r"^\[.*\]$")

# Fields are separated by a dash/pipe/bullet *surrounded by whitespace*. Requiring
# the whitespace matters: a bare hyphen also appears inside values we must not
# split on, such as the date in "Due: 2026-08-01".
_SEGMENT_SPLIT_RE = re.compile(r"\s+[-–—|·]{1,2}(?:\s+|$)")
# Metadata run with no separator at all, e.g. "Ship the deck Due: Friday".
_INLINE_META_RE = re.compile(r"\s+(?=(?:assigned\s*to|owner|due)\s*:)", re.IGNORECASE)
_OWNER_FIELD_RE = re.compile(r"^(?:assigned\s*to|owner)\s*:\s*(.*)$", re.IGNORECASE)
_DUE_FIELD_RE = re.compile(r"^due\s*(?:date)?\s*:\s*(.*)$", re.IGNORECASE)


def _clean_field(value: str) -> str:
    """Trim a parsed value, dropping unfilled template placeholders."""
    value = (value or "").strip().strip("*_` ").strip()
    if not value or _PLACEHOLDER_RE.match(value):
        return ""
    return value


def _classify_segments(segments):
    """Sort segments into task text vs. owner/due metadata."""
    text_parts, owner, due = [], "", ""
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        owner_match = _OWNER_FIELD_RE.match(segment)
        due_match = _DUE_FIELD_RE.match(segment)
        if owner_match:
            owner = owner or _clean_field(owner_match.group(1))
        elif due_match:
            due = due or _clean_field(due_match.group(1))
        else:
            text_parts.append(segment)
    return " ".join(text_parts).strip(), owner, due


def parse_action_items(md_text: str):
    """Extract Markdown checkbox tasks from a note.

    Handles the separators models actually emit — em dash, en dash, plain
    hyphen, pipe — and tolerates the metadata being absent or left as an
    unfilled template placeholder.

    Returns dicts with `text` (the task without its owner/due metadata),
    `owner`, `due`, `done`, and `raw_line` — the untouched source line, which
    is what set_checkbox() matches on to write a completion back to the file.
    """
    items = []
    for line in (md_text or "").split("\n"):
        match = _CHECKBOX_RE.match(line)
        if not match:
            continue

        text, owner, due = _classify_segments(_SEGMENT_SPLIT_RE.split(match.group(4)))
        if not owner or not due:
            # Metadata may follow the task without a separator between them
            retry_text, retry_owner, retry_due = _classify_segments(_INLINE_META_RE.split(text))
            text = retry_text or text
            owner = owner or retry_owner
            due = due or retry_due

        text = _clean_field(text)
        if not text:
            continue  # an untouched template placeholder, not a real task

        items.append({
            "text": text,
            "owner": owner,
            "due": due,
            "done": match.group(3) in ("x", "X"),
            "raw_line": line,
        })
    return items


def set_checkbox(md_text: str, raw_line: str, done: bool):
    """Tick or untick one checkbox in a note, matching `raw_line` exactly.

    Returns (new_text, changed) so callers can skip rewriting the file when
    the note has drifted and the line no longer matches.
    """
    lines = (md_text or "").split("\n")
    for index, line in enumerate(lines):
        if line != raw_line:
            continue
        match = _CHECKBOX_RE.match(line)
        if not match:
            break
        indent, bullet, _, body = match.groups()
        lines[index] = f"{indent}{bullet} [{'x' if done else ' '}] {body}"
        return "\n".join(lines), True
    return md_text, False


# ---------------------------------------------------------------------------
# Things derived from notes you've already saved
# ---------------------------------------------------------------------------

_FLASHCARD_RE = re.compile(
    r"^\s*(?:\d+[.)]\s*)?Q\s*[:.]\s*(?P<q>.+?)\s*$\n+^\s*A\s*[:.]\s*(?P<a>.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def parse_flashcards(raw: str):
    """Pull Q/A pairs out of a model response.

    Models tend to add a preamble, number the cards, or wrap them in Markdown
    even when told not to, so this tolerates all three rather than failing.
    """
    cards = []
    for match in _FLASHCARD_RE.finditer(raw or ""):
        question = match.group("q").strip().strip("*_` ").strip()
        answer = match.group("a").strip().strip("*_` ").strip()
        if question and answer:
            cards.append({"question": question, "answer": answer})
    return cards


def generate_flashcards(note_text: str, count: int = 10,
                        model_name: str = config.DEFAULT_OLLAMA_MODEL):
    """Generate study flashcards from a saved note."""
    prompt = config.FLASHCARD_PROMPT.format(count=count, note=note_text)
    response = ollama.generate(model=model_name, prompt=prompt)
    return parse_flashcards(response["response"])


def generate_followup(note_text: str, tone: str = "warm but professional",
                      model_name: str = config.DEFAULT_OLLAMA_MODEL) -> str:
    """Draft a follow-up email from a meeting, interview, or networking note."""
    prompt = config.FOLLOWUP_PROMPT.format(tone=tone, note=note_text)
    return ollama.generate(model=model_name, prompt=prompt)["response"]


def synthesize_notes(sections, prompt_template: str,
                     model_name: str = config.DEFAULT_OLLAMA_MODEL) -> str:
    """Merge several notes into one document (study guide, weekly digest, …).

    `sections` is an iterable of (title, text) pairs; each is labelled so the
    model can attribute material, and so conflicts between notes are visible.
    """
    combined = "\n\n".join(f"--- NOTE: {title} ---\n{text}" for title, text in sections)
    prompt = prompt_template.format(note=combined)
    return ollama.generate(model=model_name, prompt=prompt)["response"]


def search_notes(query: str, storage_dir: Path = config.STORAGE_DIR):
    """Perform full-text search across all saved Markdown files."""
    results = []
    if not query.strip():
        return results
    
    for filepath in storage_dir.rglob("*.md"):
        content = filepath.read_text(encoding="utf-8")
        if query.lower() in content.lower():
            snippet_idx = content.lower().find(query.lower())
            start = max(0, snippet_idx - 40)
            end = min(len(content), snippet_idx + 80)
            snippet = "..." + content[start:end].replace("\n", " ") + "..."

            # Notes live at <category>/<slug>/note.md; fall back gracefully
            # for legacy flat files saved as <category>/<slug>.md.
            rel_parts = filepath.relative_to(storage_dir).parts
            category = rel_parts[0] if len(rel_parts) > 1 else filepath.parent.name
            display_name = (
                filepath.parent.name.replace("_", " ").title()
                if filepath.name.lower() == "note.md"
                else filepath.name
            )

            results.append({
                "path": filepath,
                "name": display_name,
                "category": category,
                "snippet": snippet
            })
    return results

def convert_md_to_html(md_text: str) -> str:
    """Convert Markdown to clean HTML."""
    return markdown.markdown(md_text, extensions=['extra'])

_MD_INLINE_MARKERS = re.compile(r"(\*\*|__|\*|_|`|~~)")


def _pdf_safe(text: str) -> str:
    """PDF core fonts are Latin-1 only. Drop what they can't represent (the
    emoji used in note templates) instead of rendering it as '?' noise."""
    return text.encode("latin-1", "ignore").decode("latin-1")


def convert_md_to_pdf(md_text: str, output_path: str):
    """Render a note's Markdown to a readable PDF.

    Headings, quotes, and bullets keep their shape rather than being flattened.
    Each line is written at the left margin with an explicit line break —
    fpdf2 2.8 leaves the cursor at the right margin by default, which makes a
    following full-width cell fail with "not enough horizontal space".
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    for raw_line in md_text.split("\n"):
        line = raw_line.strip()

        if not line:
            pdf.ln(4)
            continue
        if len(line) >= 3 and set(line) <= set("-*_"):  # horizontal rule
            pdf.ln(3)
            continue

        size, style, height = 11, "", 6
        heading = re.match(r"^(#{1,6})\s*(.*)$", line)
        if heading:
            level = len(heading.group(1))
            line = heading.group(2)
            size, style, height = max(18 - 2 * level, 11), "B", 8
        elif line.startswith(">"):
            line = line.lstrip("> ").strip()
            style = "I"
        elif re.match(r"^[-*+]\s+", line):
            line = "- " + re.sub(r"^[-*+]\s+", "", line)

        text = _pdf_safe(_MD_INLINE_MARKERS.sub("", line)).strip()
        if not text:
            pdf.ln(3)
            continue

        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)
