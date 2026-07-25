import shutil
from pathlib import Path

import pytest

import storage


# --------------------------- cloud detection ---------------------------

def test_detect_providers_finds_windows_onedrive_env(tmp_path):
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    found = storage.detect_providers(home=tmp_path, env={"OneDrive": str(onedrive)},
                                     include_windows_drives=False)
    assert [p["kind"] for p in found] == ["onedrive"]
    assert found[0]["path"] == onedrive


def test_detect_providers_ignores_env_path_that_does_not_exist(tmp_path):
    found = storage.detect_providers(home=tmp_path, env={"OneDrive": str(tmp_path / "nope")},
                                     include_windows_drives=False)
    assert found == []


def test_detect_providers_finds_macos_cloudstorage_folders(tmp_path):
    cloud = tmp_path / "Library" / "CloudStorage"
    (cloud / "OneDrive-Personal").mkdir(parents=True)
    gdrive = cloud / "GoogleDrive-someone@example.com"
    (gdrive / "My Drive").mkdir(parents=True)
    (tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(parents=True)

    found = storage.detect_providers(home=tmp_path, env={}, include_windows_drives=False)
    kinds = {p["kind"] for p in found}
    assert {"onedrive", "googledrive", "icloud"} <= kinds

    # Google Drive should resolve to the "My Drive" root, not its parent
    google = next(p for p in found if p["kind"] == "googledrive")
    assert google["path"].name == "My Drive"


def test_detect_providers_dedupes_same_path(tmp_path):
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    # Both the env var and the ~/OneDrive fallback point at the same folder
    found = storage.detect_providers(home=tmp_path, env={"OneDrive": str(onedrive)},
                                     include_windows_drives=False)
    assert len(found) == 1


def test_library_path_uses_dedicated_subfolder(tmp_path):
    assert storage.library_path_for(tmp_path) == tmp_path / "EchoPad"


# ----------------------------- moving ---------------------------------

def _make_note(root: Path, category: str, slug: str, body: str = "# Note"):
    note_dir = root / category / slug
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text(body, encoding="utf-8")
    (note_dir / "recording.wav").write_bytes(b"RIFFfake")
    return note_dir


def test_move_library_moves_files_and_clears_source(tmp_path):
    src, dst = tmp_path / "old", tmp_path / "new"
    _make_note(src, "Lectures", "note_one")
    _make_note(src, "Interviews", "note_two")

    result = storage.move_library(src, dst)

    assert result["moved"] == 4  # two notes x (md + wav)
    assert result["conflicts"] == [] and result["failed"] == []
    assert (dst / "Lectures" / "note_one" / "note.md").read_text(encoding="utf-8") == "# Note"
    assert (dst / "Interviews" / "note_two" / "recording.wav").exists()
    # Originals are gone and the emptied folders pruned
    assert not (src / "Lectures" / "note_one").exists()
    assert list(src.rglob("*.md")) == []


def test_move_library_is_a_noop_for_same_directory(tmp_path):
    src = tmp_path / "notes"
    _make_note(src, "Lectures", "keep_me")
    result = storage.move_library(src, src)
    assert result["unchanged"] is True
    assert (src / "Lectures" / "keep_me" / "note.md").exists()


def test_move_library_skips_conflicts_without_overwriting(tmp_path):
    src, dst = tmp_path / "old", tmp_path / "new"
    _make_note(src, "Lectures", "dupe", body="# From source")
    _make_note(dst, "Lectures", "dupe", body="# Already at destination")

    result = storage.move_library(src, dst)

    assert len(result["conflicts"]) == 2
    assert result["moved"] == 0
    # Destination content preserved, source left intact for the user to reconcile
    assert (dst / "Lectures" / "dupe" / "note.md").read_text(encoding="utf-8") == "# Already at destination"
    assert (src / "Lectures" / "dupe" / "note.md").exists()


def test_move_library_rolls_back_and_keeps_originals_when_a_copy_fails(tmp_path, monkeypatch):
    src, dst = tmp_path / "old", tmp_path / "new"
    _make_note(src, "Lectures", "first")
    _make_note(src, "Lectures", "second")

    real_copy = shutil.copy2
    calls = {"n": 0}

    def flaky_copy(source, target, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # fail partway through
            raise OSError("disk full")
        return real_copy(source, target, *args, **kwargs)

    monkeypatch.setattr(storage.shutil, "copy2", flaky_copy)
    result = storage.move_library(src, dst)

    assert result["moved"] == 0
    assert result["failed"] and "disk full" in result["failed"][0]["error"]
    # Every original still present...
    assert len(list(src.rglob("*.md"))) == 2
    assert len(list(src.rglob("*.wav"))) == 2
    # ...and no half-copied files left behind at the destination
    assert list(dst.rglob("*.md")) == [] and list(dst.rglob("*.wav")) == []


# -------------------------- note metadata -----------------------------

def test_note_meta_round_trips_and_merges(tmp_path):
    note_dir = _make_note(tmp_path, "Lectures", "meta_note")
    md = note_dir / "note.md"

    storage.write_note_meta(md, title="Real Title: With Punctuation", tags="a, b")
    storage.write_note_meta(md, word_count=42)  # merges, doesn't clobber

    meta = storage.read_note_meta(md)
    assert meta["title"] == "Real Title: With Punctuation"
    assert meta["tags"] == "a, b"
    assert meta["word_count"] == 42
    assert (note_dir / "meta.json").exists()


def test_read_note_meta_tolerates_missing_and_corrupt_files(tmp_path):
    note_dir = _make_note(tmp_path, "Lectures", "no_meta")
    md = note_dir / "note.md"
    assert storage.read_note_meta(md) == {}

    (note_dir / "meta.json").write_text("{not json", encoding="utf-8")
    assert storage.read_note_meta(md) == {}


def test_note_meta_ignores_unknown_fields(tmp_path):
    md = _make_note(tmp_path, "Lectures", "n") / "note.md"
    storage.write_note_meta(md, title="Keep", injected="drop me")
    assert storage.read_note_meta(md) == {"title": "Keep"}


def test_meta_path_for_legacy_flat_note(tmp_path):
    category = tmp_path / "Lectures"
    category.mkdir()
    md = category / "old_note.md"
    assert storage.meta_path(md) == category / "old_note.meta.json"


# ---------------------------- renaming --------------------------------

def test_slugify_strips_unsafe_characters():
    assert storage.slugify('Bio 101: Mitosis / Meiosis?') == "bio_101_mitosis_meiosis"
    assert storage.slugify("   ") == "untitled"


def test_unique_slug_avoids_collisions(tmp_path):
    (tmp_path / "notes").mkdir()
    assert storage.unique_slug(tmp_path, "notes") == "notes_2"
    assert storage.unique_slug(tmp_path, "fresh") == "fresh"


def test_rename_note_renames_folder_and_returns_index_key(tmp_path):
    note_dir = _make_note(tmp_path, "Lectures", "old_title")
    new_md, new_key = storage.rename_note(note_dir / "note.md", "Brand New Title")

    assert new_md == tmp_path / "Lectures" / "brand_new_title" / "note.md"
    assert new_key == "brand_new_title/note.md"
    assert new_md.exists() and (new_md.parent / "recording.wav").exists()
    assert not note_dir.exists()


def test_rename_note_handles_legacy_flat_layout(tmp_path):
    category = tmp_path / "Lectures"
    category.mkdir(parents=True)
    (category / "old_note.md").write_text("# Legacy", encoding="utf-8")
    (category / "old_note.wav").write_bytes(b"RIFFfake")

    new_md, new_key = storage.rename_note(category / "old_note.md", "Fresh Name")

    assert new_md == category / "fresh_name.md"
    assert new_key == "fresh_name.md"
    assert (category / "fresh_name.wav").exists()
    assert not (category / "old_note.md").exists()


def test_rename_note_refuses_to_clobber_existing_note(tmp_path):
    _make_note(tmp_path, "Lectures", "taken")
    note_dir = _make_note(tmp_path, "Lectures", "moving")

    with pytest.raises(FileExistsError):
        storage.rename_note(note_dir / "note.md", "Taken")

    assert (note_dir / "note.md").exists()  # untouched
