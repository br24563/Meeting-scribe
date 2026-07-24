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

def test_md_to_html_conversion():
    md = "# Hello World"
    html = engine.convert_md_to_html(md)
    assert "<h1>Hello World</h1>" in html
