"""SQLite index over the notes, plus persisted user preferences.

The Markdown + audio files under STORAGE_DIR remain the portable source of
truth; this index just makes search, tagging, and cross-category listing fast
without re-reading every file on each interaction.

The index deliberately lives *outside* the notes folder, in APP_CONFIG_DIR.
Cloud-sync clients (OneDrive, Google Drive) can lock or partially upload a
live SQLite file, which risks corruption, and the index is fully rebuildable
from the .md files anyway — so notes sync, and the index stays machine-local.
"""
import contextlib
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import config
import storage

LEGACY_DB_NAME = "echopad.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    template TEXT,
    tags TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, filename)
);
CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the original schema shipped. Applied to existing
# databases on connect so upgrades don't need a manual migration step.
COLUMN_MIGRATIONS = (
    ("word_count", "ALTER TABLE notes ADD COLUMN word_count INTEGER DEFAULT 0"),
)


def index_path(storage_dir=None) -> Path:
    """Where the index for a given notes folder lives (machine-local).

    Keyed by the notes path so switching between, say, a local folder and a
    OneDrive folder keeps each library's tags intact instead of clobbering.
    """
    storage_dir = Path(storage_dir) if storage_dir else config.STORAGE_DIR
    try:
        resolved = str(storage_dir.resolve()).lower()
    except OSError:
        resolved = str(storage_dir).lower()
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:12]
    return config.APP_CONFIG_DIR / f"index-{digest}.db"


def _resolve(db_path, storage_dir):
    """Resolve the (index, notes) paths lazily, so a location change mid-session
    is picked up without re-importing this module."""
    storage_dir = Path(storage_dir) if storage_dir else config.STORAGE_DIR
    db_path = Path(db_path) if db_path else index_path(storage_dir)
    return db_path, storage_dir


def relative_key(md_path: Path, storage_dir=None):
    """Derive the (category, filename) key used to index a note, from its
    .md path. `filename` is the path relative to the category folder (e.g.
    "organic_chem_review/note.md" for the per-note folder layout, or plain
    "old_note.md" for notes saved before that layout existed)."""
    _, storage_dir = _resolve(None, storage_dir)
    rel_parts = Path(md_path).relative_to(storage_dir).parts
    if len(rel_parts) < 2:
        return Path(md_path).parent.name, Path(md_path).name
    return rel_parts[0], "/".join(rel_parts[1:])


def get_connection(db_path=None) -> sqlite3.Connection:
    db_path, _ = _resolve(db_path, None)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(notes)")}
    for column, statement in COLUMN_MIGRATIONS:
        if column not in existing:
            conn.execute(statement)
    return conn


@contextlib.contextmanager
def _connect(db_path=None):
    """Open a connection, commit on success, and always close it.

    `with sqlite3.connect(...)` commits but does *not* close — and a leaked
    handle keeps the database file locked on Windows (which breaks moving or
    renaming it) while slowly exhausting file handles across a long session.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate_legacy_index(storage_dir=None, db_path=None) -> bool:
    """Earlier versions kept the index inside the notes folder. Adopt it once
    so tags survive the upgrade, then set the old file aside."""
    db_path, storage_dir = _resolve(db_path, storage_dir)
    legacy = storage_dir / LEGACY_DB_NAME
    if db_path.exists() or not legacy.exists():
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(legacy, db_path)
    except OSError:
        return False
    # Set the old file aside so it isn't adopted again. The copy above already
    # preserved the data, so failing to rename is not worth aborting over.
    with contextlib.suppress(OSError):
        legacy.rename(legacy.with_name(legacy.name + ".migrated"))
    return True


def add_note(title: str, category: str, filename: str, template: str = "", tags: str = "",
             word_count: int = 0, created_at: str = None, db_path=None) -> None:
    """Record a saved note in the index. `created_at` defaults to now, and is
    passed explicitly when restoring a note's original date from its sidecar."""
    columns = "title, category, filename, template, tags, word_count"
    values = [title, category, filename, template, tags, word_count]
    if created_at:
        columns += ", created_at"
        values.append(created_at)
    placeholders = ", ".join("?" * len(values))
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO notes ({columns}) VALUES ({placeholders})",
            values,
        )


def delete_note(category: str, filename: str, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM notes WHERE category = ? AND filename = ?",
            (category, filename),
        )


def rename_note(category: str, old_filename: str, new_filename: str, new_title: str,
                db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE notes SET filename = ?, title = ? WHERE category = ? AND filename = ?",
            (new_filename, new_title, category, old_filename),
        )


def update_tags(category: str, filename: str, tags: str, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE notes SET tags = ? WHERE category = ? AND filename = ?",
            (tags, category, filename),
        )


def update_word_count(category: str, filename: str, word_count: int, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE notes SET word_count = ? WHERE category = ? AND filename = ?",
            (word_count, category, filename),
        )


def get_note(category: str, filename: str, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM notes WHERE category = ? AND filename = ?",
            (category, filename),
        ).fetchone()
    return dict(row) if row else None


def recent_notes(limit: int = 10, db_path=None):
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def counts_by_category(db_path=None):
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM notes GROUP BY category"
        ).fetchall()
    return {row["category"]: row["n"] for row in rows}


def total_word_count(db_path=None) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COALESCE(SUM(word_count), 0) AS total FROM notes").fetchone()
    return int(row["total"] or 0)


def all_tags(db_path=None):
    """Distinct tags across all notes, without pulling full note rows."""
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT tags FROM notes WHERE tags != ''").fetchall()
    tags = set()
    for row in rows:
        tags.update(t.strip() for t in row["tags"].split(",") if t.strip())
    return sorted(tags)


def get_pref(key: str, default: str = None, db_path=None) -> str:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_pref(key: str, value: str, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_pref_json(key: str, default=None, db_path=None):
    """Convenience wrapper for preferences that store a list/dict as JSON."""
    raw = get_pref(key, db_path=db_path)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def set_pref_json(key: str, value, db_path=None) -> None:
    set_pref(key, json.dumps(value), db_path=db_path)


def search(query: str, category: str = None, tag: str = None, db_path=None):
    """Search notes by title/tags. For matching on note body content, use
    engine.search_notes, which scans file contents directly."""
    sql = "SELECT * FROM notes WHERE 1=1"
    params = []
    if query:
        sql += " AND (title LIKE ? OR tags LIKE ?)"
        params += [f"%{query}%", f"%{query}%"]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    sql += " ORDER BY created_at DESC"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def prune_missing(storage_dir=None, db_path=None) -> int:
    """Remove index entries whose .md file is no longer on disk — e.g. its
    folder was renamed, moved, or deleted directly in a file explorer rather
    than through the app. Paired with rebuild_from_disk(), this means a
    rename is picked up as "delete old entry, index the new folder"."""
    db_path, storage_dir = _resolve(db_path, storage_dir)
    removed = 0
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT category, filename FROM notes").fetchall()
    for row in rows:
        if not (storage_dir / row["category"] / row["filename"]).exists():
            delete_note(row["category"], row["filename"], db_path=db_path)
            removed += 1
    return removed


def rebuild_from_disk(storage_dir=None, db_path=None) -> int:
    """Index any .md files on disk that aren't already tracked (e.g. files
    dropped in manually, synced down from another machine, or notes created
    before the index existed). Handles both the per-note-folder layout
    (category/slug/note.md) and legacy flat files (category/slug.md).

    A note's own meta.json is the source of truth for its title, tags, and
    template, so those survive moving the library, syncing to another
    computer, or deleting the index. Only notes saved before sidecars existed
    fall back to deriving a title from the folder name.
    """
    db_path, storage_dir = _resolve(db_path, storage_dir)
    added = 0
    for filepath in storage_dir.rglob("*.md"):
        category, filename = relative_key(filepath, storage_dir)
        with _connect(db_path) as conn:
            existing = conn.execute(
                "SELECT 1 FROM notes WHERE category = ? AND filename = ?",
                (category, filename),
            ).fetchone()
        if existing:
            continue

        try:
            word_count = len(filepath.read_text(encoding="utf-8").split())
        except OSError:
            word_count = 0

        if filepath.name.lower() == "note.md":
            fallback_title = filepath.parent.name.replace("_", " ").title()
        else:
            fallback_title = filepath.stem.replace("_", " ").title()

        meta = storage.read_note_meta(filepath)
        add_note(
            title=meta.get("title") or fallback_title,
            category=category,
            filename=filename,
            template=meta.get("template", ""),
            tags=meta.get("tags", ""),
            word_count=meta.get("word_count") or word_count,
            created_at=meta.get("created_at"),
            db_path=db_path,
        )
        added += 1
    return added
