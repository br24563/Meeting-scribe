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
