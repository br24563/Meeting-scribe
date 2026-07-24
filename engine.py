import os
import re
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

def transcribe_audio(audio_bytes, model_size: str = config.DEFAULT_WHISPER_MODEL, translate: bool = False) -> str:
    """Transcribe or translate audio locally using faster-whisper."""
    temp_path = "temp_recording.wav"
    with open(temp_path, "wb") as f:
        f.write(audio_bytes.read() if hasattr(audio_bytes, "read") else audio_bytes)

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        task = "translate" if translate else "transcribe"
        segments, _ = model.transcribe(temp_path, beam_size=5, task=task)
        full_transcript = " ".join([segment.text.strip() for segment in segments])
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return full_transcript

def generate_summary(transcript: str, template_key: str = "Meeting", model_name: str = config.DEFAULT_OLLAMA_MODEL) -> str:
    """Generate structured summary using selected template and Ollama."""
    template = config.TEMPLATES.get(template_key, config.TEMPLATES["Meeting"])
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
            results.append({
                "path": filepath,
                "name": filepath.name,
                "category": filepath.parent.name,
                "snippet": snippet
            })
    return results

def convert_md_to_html(md_text: str) -> str:
    """Convert Markdown to clean HTML."""
    return markdown.markdown(md_text, extensions=['extra'])

def convert_md_to_pdf(md_text: str, output_path: str):
    """Convert raw markdown text to standard PDF."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    
    # Strip markdown headers/bold syntax for simple PDF export
    clean_text = re.sub(r'[#*`>-]', '', md_text)
    
    for line in clean_text.split('\n'):
        pdf.multi_cell(0, 8, txt=line.encode('latin-1', 'replace').decode('latin-1'))
    pdf.output(output_path)
