"""Importing existing notes from other file formats."""
import pytest

import importers


# ------------------------------ plain text ----------------------------

def test_reads_utf8_text_and_markdown():
    text, warnings = importers.extract_text("notes.txt", "Hello — em dash".encode("utf-8"))
    assert text == "Hello — em dash"
    assert warnings == []

    text, _ = importers.extract_text("notes.md", b"# Heading\n\nBody")
    assert text.startswith("# Heading")


def test_falls_back_to_cp1252_without_mangling_it_as_utf16():
    """Regression guard: UTF-16 decodes almost any even-length byte string, so
    trying it speculatively turned cp1252 text into mojibake."""
    text, _ = importers.extract_text("notes.txt", "Café".encode("cp1252"))
    assert text == "Café"


def test_honours_a_utf16_byte_order_mark():
    text, _ = importers.extract_text("notes.txt", "Résumé notes".encode("utf-16"))
    assert text == "Résumé notes"


def test_strips_a_utf8_byte_order_mark():
    text, _ = importers.extract_text("notes.txt", "﻿Heading".encode("utf-8"))
    assert text == "Heading"


# --------------------------------- PDF --------------------------------

def test_reads_text_from_a_pdf(tmp_path):
    """Built with fpdf2 (already a dependency) so the test is self-contained."""
    pytest.importorskip("pypdf")
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, "Mitochondria are the powerhouse of the cell.",
                   new_x="LMARGIN", new_y="NEXT")
    target = tmp_path / "handout.pdf"
    pdf.output(str(target))

    text, warnings = importers.extract_text("handout.pdf", target.read_bytes())
    assert "powerhouse" in text
    assert warnings == []


def test_flags_a_pdf_with_no_text_layer(tmp_path):
    """A scanned PDF extracts nothing useful — say so, and point at OCR."""
    pytest.importorskip("pypdf")
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()  # an empty page: no text layer
    target = tmp_path / "scan.pdf"
    pdf.output(str(target))

    text, warnings = importers.extract_text("scan.pdf", target.read_bytes())
    assert text == ""
    assert warnings and "scan" in warnings[0].lower()


def test_rejects_bytes_that_are_not_a_pdf():
    pytest.importorskip("pypdf")
    with pytest.raises(importers.ImportFailed):
        importers.extract_text("broken.pdf", b"definitely not a pdf")


# -------------------------------- DOCX --------------------------------

def test_reads_paragraphs_and_tables_from_docx(tmp_path):
    docx = pytest.importorskip("docx")

    document = docx.Document()
    document.add_paragraph("Lecture 4: Thermodynamics")
    document.add_paragraph("")  # blank paragraphs are skipped
    document.add_paragraph("The first law is conservation of energy.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Symbol"
    table.rows[0].cells[1].text = "Meaning"
    target = tmp_path / "lecture.docx"
    document.save(str(target))

    text, warnings = importers.extract_text("lecture.docx", target.read_bytes())
    assert "Thermodynamics" in text
    assert "conservation of energy" in text
    assert "Symbol | Meaning" in text  # table flattened readably
    assert warnings == []


def test_rejects_bytes_that_are_not_a_docx():
    pytest.importorskip("docx")
    with pytest.raises(importers.ImportFailed):
        importers.extract_text("broken.docx", b"not a docx at all")


# ------------------------- unsupported formats ------------------------

def test_legacy_doc_gets_a_specific_message():
    with pytest.raises(importers.ImportFailed, match=r"\.docx"):
        importers.extract_text("old.doc", b"")


def test_slide_decks_are_redirected_to_pdf():
    with pytest.raises(importers.ImportFailed, match="PDF"):
        importers.extract_text("deck.pptx", b"")


def test_unknown_extension_lists_what_is_supported():
    with pytest.raises(importers.ImportFailed, match=r"\.pdf"):
        importers.extract_text("mystery.xyz", b"")


# ------------------------------ metadata ------------------------------

def test_upload_types_are_bare_extensions_for_streamlit():
    assert "pdf" in importers.UPLOAD_TYPES
    assert "jpg" in importers.UPLOAD_TYPES
    assert all(not t.startswith(".") for t in importers.UPLOAD_TYPES)


def test_describe_source_names_the_extraction_method():
    assert "OCR" in importers.describe_source("board.jpg")
    assert "PDF" in importers.describe_source("slides.pdf")
    assert "Word" in importers.describe_source("handout.docx")
    assert "imported file" in importers.describe_source("notes.txt")
