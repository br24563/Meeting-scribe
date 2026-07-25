"""Storage-location resolution and index relocation.

These reload `config`/`db` under a patched environment, since both read the
environment and the home directory at import time.
"""
import importlib
import json


def _reload(monkeypatch, tmp_path, storage_env=None):
    monkeypatch.setenv("ECHOPAD_CONFIG_DIR", str(tmp_path / "appconfig"))
    if storage_env is None:
        monkeypatch.delenv("ECHOPAD_STORAGE_DIR", raising=False)
    else:
        monkeypatch.setenv("ECHOPAD_STORAGE_DIR", str(storage_env))
    monkeypatch.chdir(tmp_path)

    import config
    import db
    config = importlib.reload(config)
    db = importlib.reload(db)
    return config, db


def test_env_var_wins_and_is_reported_as_pinned(monkeypatch, tmp_path):
    target = tmp_path / "from_env"
    config, _ = _reload(monkeypatch, tmp_path, storage_env=target)

    assert config.STORAGE_DIR == target
    assert config.storage_dir_is_pinned() is True


def test_defaults_to_local_notes_folder(monkeypatch, tmp_path):
    config, _ = _reload(monkeypatch, tmp_path)

    assert config.STORAGE_DIR == config.DEFAULT_STORAGE_DIR
    assert config.storage_dir_is_pinned() is False
    assert (tmp_path / "notes").is_dir()


def test_saved_location_is_persisted_and_used_next_launch(monkeypatch, tmp_path):
    config, _ = _reload(monkeypatch, tmp_path)
    chosen = tmp_path / "OneDrive" / "EchoPad"

    config.set_storage_dir(chosen)

    assert config.STORAGE_DIR == chosen  # applied in place, no restart needed
    assert chosen.is_dir()
    saved = json.loads(config.LOCATION_FILE.read_text(encoding="utf-8"))
    assert saved["storage_dir"] == str(chosen)

    # A fresh import (i.e. next launch) picks the saved location back up
    config2, _ = _reload(monkeypatch, tmp_path)
    assert config2.STORAGE_DIR == chosen


def test_env_var_overrides_a_saved_location(monkeypatch, tmp_path):
    config, _ = _reload(monkeypatch, tmp_path)
    config.set_storage_dir(tmp_path / "saved")

    pinned = tmp_path / "docker_mount"
    config2, _ = _reload(monkeypatch, tmp_path, storage_env=pinned)
    assert config2.STORAGE_DIR == pinned


def test_index_lives_outside_notes_folder_and_is_per_location(monkeypatch, tmp_path):
    config, db = _reload(monkeypatch, tmp_path)

    local_index = db.index_path(tmp_path / "local_notes")
    cloud_index = db.index_path(tmp_path / "OneDrive" / "EchoPad")

    assert local_index.parent == config.APP_CONFIG_DIR
    assert cloud_index.parent == config.APP_CONFIG_DIR
    # Distinct libraries keep distinct indexes, so tags don't clobber each other
    assert local_index != cloud_index


def test_db_follows_a_location_change_without_reimport(monkeypatch, tmp_path):
    config, db = _reload(monkeypatch, tmp_path)

    first = tmp_path / "library_one"
    config.set_storage_dir(first)
    db.add_note("In First", "Lectures", "a/note.md")
    assert [n["title"] for n in db.recent_notes()] == ["In First"]

    second = tmp_path / "library_two"
    config.set_storage_dir(second)
    # Same process, no reimport: db should now be reading the other library's index
    assert db.recent_notes() == []

    config.set_storage_dir(first)
    assert [n["title"] for n in db.recent_notes()] == ["In First"]


def test_legacy_index_is_adopted_once_preserving_tags(monkeypatch, tmp_path):
    config, db = _reload(monkeypatch, tmp_path)
    notes_dir = tmp_path / "notes"

    # Simulate an older install whose index sat inside the notes folder
    legacy = notes_dir / db.LEGACY_DB_NAME
    db.add_note("Old Note", "Lectures", "old/note.md", tags="orgo", db_path=legacy)

    assert db.migrate_legacy_index(storage_dir=notes_dir) is True
    adopted = db.get_note("Lectures", "old/note.md", db_path=db.index_path(notes_dir))
    assert adopted["tags"] == "orgo"
    assert not legacy.exists()  # set aside, so it isn't adopted twice
    assert legacy.with_name(legacy.name + ".migrated").exists()

    # Second call is a no-op now that a current index exists
    assert db.migrate_legacy_index(storage_dir=notes_dir) is False


def test_index_file_is_not_left_locked_after_writes(monkeypatch, tmp_path):
    """Regression guard: `with sqlite3.connect(...)` commits but doesn't close,
    and a leaked handle keeps the file locked on Windows — which silently broke
    the legacy-index migration and would block moving the library."""
    _, db = _reload(monkeypatch, tmp_path)
    db_path = tmp_path / "locked.db"

    db.add_note("A", "Lectures", "a/note.md", db_path=db_path)
    db.update_tags("Lectures", "a/note.md", "tag", db_path=db_path)
    db.set_pref("k", "v", db_path=db_path)
    db.recent_notes(db_path=db_path)

    # If any connection were still open, this raises PermissionError on Windows
    moved = db_path.with_name("moved.db")
    db_path.rename(moved)
    assert moved.exists()


def test_word_count_column_is_added_to_an_existing_database(monkeypatch, tmp_path):
    import sqlite3
    _, db = _reload(monkeypatch, tmp_path)
    db_path = tmp_path / "old_schema.db"

    # A database created before word_count existed
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE notes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                   category TEXT NOT NULL, filename TEXT NOT NULL, template TEXT,
                   tags TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')),
                   UNIQUE(category, filename))"""
        )
        conn.execute("INSERT INTO notes (title, category, filename) VALUES ('Pre-existing', 'Lectures', 'a.md')")

    # Connecting through db.py migrates the schema in place, keeping the row
    assert db.total_word_count(db_path=db_path) == 0
    db.update_word_count("Lectures", "a.md", 321, db_path=db_path)
    assert db.total_word_count(db_path=db_path) == 321
    assert db.get_note("Lectures", "a.md", db_path=db_path)["title"] == "Pre-existing"


def test_rebuild_from_disk_records_word_counts(monkeypatch, tmp_path):
    _, db = _reload(monkeypatch, tmp_path)
    notes_dir = tmp_path / "library"
    note_dir = notes_dir / "Lectures" / "counted"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text("one two three four five", encoding="utf-8")

    db_path = tmp_path / "idx.db"
    assert db.rebuild_from_disk(storage_dir=notes_dir, db_path=db_path) == 1
    assert db.total_word_count(db_path=db_path) == 5


def test_rebuild_recovers_title_and_tags_from_sidecar(monkeypatch, tmp_path):
    """The whole point of meta.json: deleting the index (or moving/syncing the
    library, which lands on a fresh index) must not lose tags or the real title."""
    _, db = _reload(monkeypatch, tmp_path)
    import storage

    notes_dir = tmp_path / "library"
    note_dir = notes_dir / "Lectures" / "bio_101_mitosis_meiosis"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text("# Bio\n\nwords here", encoding="utf-8")
    storage.write_note_meta(
        note_dir / "note.md",
        title="Bio 101: Mitosis / Meiosis?", tags="bio, midterm",
        template="Lecture", created_at="2026-01-02 03:04:05",
    )

    db_path = tmp_path / "fresh_index.db"  # as if the index were gone
    assert db.rebuild_from_disk(storage_dir=notes_dir, db_path=db_path) == 1

    row = db.get_note("Lectures", "bio_101_mitosis_meiosis/note.md", db_path=db_path)
    assert row["title"] == "Bio 101: Mitosis / Meiosis?"  # not the folder-name guess
    assert row["tags"] == "bio, midterm"
    assert row["template"] == "Lecture"
    assert row["created_at"] == "2026-01-02 03:04:05"


def test_rebuild_falls_back_to_folder_name_without_a_sidecar(monkeypatch, tmp_path):
    _, db = _reload(monkeypatch, tmp_path)
    notes_dir = tmp_path / "library"
    note_dir = notes_dir / "Lectures" / "older_note"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text("legacy note", encoding="utf-8")

    db_path = tmp_path / "idx.db"
    db.rebuild_from_disk(storage_dir=notes_dir, db_path=db_path)
    row = db.get_note("Lectures", "older_note/note.md", db_path=db_path)
    assert row["title"] == "Older Note"
    assert row["tags"] == ""


def test_moving_the_library_preserves_tags_and_titles(monkeypatch, tmp_path):
    """Regression guard for the flaw an end-to-end run caught: relocating the
    library lands on a per-location index, so metadata has to come from disk."""
    config, db = _reload(monkeypatch, tmp_path)
    import storage

    start = tmp_path / "local_notes"
    config.set_storage_dir(start)
    note_dir = start / "Lectures" / "bio_101"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text("# Bio", encoding="utf-8")
    db.add_note("Bio 101: Mitosis", "Lectures", "bio_101/note.md", tags="bio, midterm")
    storage.write_note_meta(note_dir / "note.md", title="Bio 101: Mitosis", tags="bio, midterm")

    target = storage.library_path_for(tmp_path / "OneDrive")
    assert storage.move_library(start, target)["failed"] == []
    config.set_storage_dir(target)
    db.prune_missing()
    db.rebuild_from_disk()

    row = db.get_note("Lectures", "bio_101/note.md")
    assert row["title"] == "Bio 101: Mitosis"
    assert row["tags"] == "bio, midterm"


def test_rename_note_updates_index_key_and_title(monkeypatch, tmp_path):
    _, db = _reload(monkeypatch, tmp_path)
    db_path = tmp_path / "idx.db"
    db.add_note("Old Title", "Lectures", "old_title/note.md", tags="keep", db_path=db_path)

    db.rename_note("Lectures", "old_title/note.md", "new_title/note.md", "New Title", db_path=db_path)

    assert db.get_note("Lectures", "old_title/note.md", db_path=db_path) is None
    renamed = db.get_note("Lectures", "new_title/note.md", db_path=db_path)
    assert renamed["title"] == "New Title"
    assert renamed["tags"] == "keep"  # tags survive a rename
