import db


def test_add_note_and_recent(tmp_path):
    db_path = tmp_path / "test.db"
    db.add_note("Midterm Review", "Lectures", "midterm_review.md", template="Lecture", tags="orgo, ch4", db_path=db_path)

    recent = db.recent_notes(db_path=db_path)
    assert len(recent) == 1
    assert recent[0]["title"] == "Midterm Review"
    assert recent[0]["tags"] == "orgo, ch4"


def test_counts_by_category(tmp_path):
    db_path = tmp_path / "test.db"
    db.add_note("Note A", "Lectures", "a.md", db_path=db_path)
    db.add_note("Note B", "Lectures", "b.md", db_path=db_path)
    db.add_note("Note C", "Interviews", "c.md", db_path=db_path)

    counts = db.counts_by_category(db_path=db_path)
    assert counts == {"Lectures": 2, "Interviews": 1}


def test_search_by_title_and_tag(tmp_path):
    db_path = tmp_path / "test.db"
    db.add_note("Acme Corp Debrief", "Interviews", "acme.md", tags="acme, careerfair", db_path=db_path)
    db.add_note("Study Group Sync", "Meetings", "sync.md", tags="study", db_path=db_path)

    by_title = db.search("Acme", db_path=db_path)
    assert len(by_title) == 1
    assert by_title[0]["filename"] == "acme.md"

    by_tag = db.search("", tag="study", db_path=db_path)
    assert len(by_tag) == 1
    assert by_tag[0]["filename"] == "sync.md"


def test_update_tags(tmp_path):
    db_path = tmp_path / "test.db"
    db.add_note("Note A", "Lectures", "a.md", db_path=db_path)
    db.update_tags("Lectures", "a.md", "newtag", db_path=db_path)

    results = db.search("", category="Lectures", db_path=db_path)
    assert results[0]["tags"] == "newtag"


def test_delete_note(tmp_path):
    db_path = tmp_path / "test.db"
    db.add_note("Note A", "Lectures", "a.md", db_path=db_path)
    db.add_note("Note B", "Lectures", "b.md", db_path=db_path)

    db.delete_note("Lectures", "a.md", db_path=db_path)

    remaining = db.recent_notes(db_path=db_path)
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "b.md"


def test_prune_missing_then_rebuild_handles_rename(tmp_path):
    db_path = tmp_path / "test.db"
    old_dir = tmp_path / "Lectures" / "old_title"
    old_dir.mkdir(parents=True)
    (old_dir / "note.md").write_text("# Old Title", encoding="utf-8")
    db.rebuild_from_disk(storage_dir=tmp_path, db_path=db_path)
    assert db.recent_notes(db_path=db_path)[0]["title"] == "Old Title"

    # Simulate renaming the note's folder in a file explorer
    new_dir = tmp_path / "Lectures" / "new_title"
    old_dir.rename(new_dir)

    removed = db.prune_missing(storage_dir=tmp_path, db_path=db_path)
    assert removed == 1
    added = db.rebuild_from_disk(storage_dir=tmp_path, db_path=db_path)
    assert added == 1

    notes = db.recent_notes(db_path=db_path)
    assert len(notes) == 1
    assert notes[0]["title"] == "New Title"
    assert notes[0]["filename"] == "new_title/note.md"


def test_rebuild_from_disk(tmp_path):
    db_path = tmp_path / "test.db"
    cat_dir = tmp_path / "Lectures"
    cat_dir.mkdir()
    (cat_dir / "manual_note.md").write_text("# Manual Note", encoding="utf-8")

    added = db.rebuild_from_disk(storage_dir=tmp_path, db_path=db_path)
    assert added == 1

    # Running it again should be a no-op since the note is already indexed
    added_again = db.rebuild_from_disk(storage_dir=tmp_path, db_path=db_path)
    assert added_again == 0


def test_relative_key_per_note_folder(tmp_path):
    md_path = tmp_path / "Lectures" / "organic_chem_review" / "note.md"
    category, filename = db.relative_key(md_path, storage_dir=tmp_path)
    assert category == "Lectures"
    assert filename == "organic_chem_review/note.md"


def test_relative_key_legacy_flat(tmp_path):
    md_path = tmp_path / "Lectures" / "organic_chem_review.md"
    category, filename = db.relative_key(md_path, storage_dir=tmp_path)
    assert category == "Lectures"
    assert filename == "organic_chem_review.md"


def test_rebuild_from_disk_per_note_folder(tmp_path):
    db_path = tmp_path / "test.db"
    note_dir = tmp_path / "Lectures" / "organic_chem_review"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text("# Organic Chem Review", encoding="utf-8")

    added = db.rebuild_from_disk(storage_dir=tmp_path, db_path=db_path)
    assert added == 1

    notes = db.recent_notes(db_path=db_path)
    assert notes[0]["title"] == "Organic Chem Review"
    assert notes[0]["category"] == "Lectures"
    assert notes[0]["filename"] == "organic_chem_review/note.md"

    # Safe to delete/rebuild using the indexed key
    db.delete_note("Lectures", "organic_chem_review/note.md", db_path=db_path)
    assert db.recent_notes(db_path=db_path) == []
