import pytest
from pathlib import Path
import engine

def test_full_text_search(tmp_path):
    # Create test markdown file
    test_file = tmp_path / "test_note.md"
    test_file.write_text("This note discusses vector search and FAISS.", encoding="utf-8")

    results = engine.search_notes("vector", storage_dir=tmp_path)
    assert len(results) == 1
    assert results[0]["name"] == "test_note.md"

def test_full_text_search_per_note_folder(tmp_path):
    # Notes saved by the app live at <category>/<slug>/note.md
    note_dir = tmp_path / "Lectures" / "vector_search_review"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text("This note discusses vector search and FAISS.", encoding="utf-8")

    results = engine.search_notes("vector", storage_dir=tmp_path)
    assert len(results) == 1
    assert results[0]["name"] == "Vector Search Review"
    assert results[0]["category"] == "Lectures"

def test_md_to_html_conversion():
    md = "# Hello World"
    html = engine.convert_md_to_html(md)
    assert "<h1>Hello World</h1>" in html


def test_md_to_pdf_renders_a_realistic_multiline_note(tmp_path):
    """Regression guard: a full note has many lines, headings, quotes, rules and
    emoji. fpdf2 2.8 leaves the cursor at the right margin after each cell, so a
    naive full-width multi_cell loop raises "not enough horizontal space" on the
    second line — and the template emoji can't be encoded by the core fonts."""
    note = (
        "# Organic Chemistry Midterm Review\n"
        "*Category: Lectures*\n\n"
        "> 💡 **Core Thesis**\n"
        "> Reaction mechanisms follow electron flow.\n\n"
        "---\n"
        "### 📖 Key Concepts\n"
        "* **Nucleophile:** an electron-rich species.\n"
        "* **Electrophile:** electron-poor, accepts a pair.\n\n"
        "- [ ] Review chapter 4 problems\n"
    )
    out = tmp_path / "note.pdf"
    engine.convert_md_to_pdf(note, str(out))

    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
    assert out.stat().st_size > 500  # real content, not an empty page


def test_md_to_pdf_handles_empty_and_symbol_only_input(tmp_path):
    for content in ("", "\n\n\n", "---\n***\n", "😀🎉"):
        out = tmp_path / "edge.pdf"
        engine.convert_md_to_pdf(content, str(out))
        assert out.read_bytes().startswith(b"%PDF")
