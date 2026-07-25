"""SQLite metadata index for notes.

The Markdown + audio files under STORAGE_DIR remain the portable source of
truth. This index just makes search, tagging, and cross-category listing
fast without re-reading every file on each interaction.
"""
import sqlite3
from pathlib import Path

import config

DB_PATH = config.STORAGE_DIR / "echopad.db"

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
"""


def relative_key(md_path: Path, storage_dir: Path = config.STORAGE_DIR):
    """Derive the (category, filename) key used to index a note, from its
    .md path. `filename` is the path relative to the category folder (e.g.
    "organic_chem_review/note.md" for the per-note folder layout, or plain
    "old_note.md" for notes saved before that layout existed)."""
    rel_parts = md_path.relative_to(storage_dir).parts
    if len(rel_parts) < 2:
        return md_path.parent.name, md_path.name
    return rel_parts[0], "/".join(rel_parts[1:])


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_note(title: str, category: str, filename: str, template: str = "", tags: str = "",
             db_path: Path = DB_PATH) -> None:
    """Record a saved note in the index (no-op if already present)."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO notes (title, category, filename, template, tags)
               VALUES (?, ?, ?, ?, ?)""",
            (title, category, filename, template, tags),
        )


def delete_note(category: str, filename: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM notes WHERE category = ? AND filename = ?",
            (category, filename),
        )


def update_tags(category: str, filename: str, tags: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE notes SET tags = ? WHERE category = ? AND filename = ?",
            (tags, category, filename),
        )


def get_note(category: str, filename: str, db_path: Path = DB_PATH):
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM notes WHERE category = ? AND filename = ?",
            (category, filename),
        ).fetchone()
    return dict(row) if row else None


def recent_notes(limit: int = 10, db_path: Path = DB_PATH):
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def counts_by_category(db_path: Path = DB_PATH):
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM notes GROUP BY category"
        ).fetchall()
    return {row["category"]: row["n"] for row in rows}


def search(query: str, category: str = None, tag: str = None, db_path: Path = DB_PATH):
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
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def prune_missing(storage_dir: Path = config.STORAGE_DIR, db_path: Path = DB_PATH) -> int:
    """Remove index entries whose .md file is no longer on disk — e.g. its
    folder was renamed, moved, or deleted directly in a file explorer rather
    than through the app. Paired with rebuild_from_disk(), this means a
    rename is picked up as "delete old entry, index the new folder"."""
    removed = 0
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT category, filename FROM notes").fetchall()
    for row in rows:
        if not (storage_dir / row["category"] / row["filename"]).exists():
            delete_note(row["category"], row["filename"], db_path=db_path)
            removed += 1
    return removed


def rebuild_from_disk(storage_dir: Path = config.STORAGE_DIR, db_path: Path = DB_PATH) -> int:
    """Re-index any .md files on disk that aren't already tracked (e.g. files
    dropped in manually, or notes created before the index existed). Handles
    both the per-note-folder layout (category/slug/note.md) and legacy flat
    files (category/slug.md) saved before it existed."""
    added = 0
    for filepath in storage_dir.rglob("*.md"):
        category, filename = relative_key(filepath, storage_dir)
        with get_connection(db_path) as conn:
            existing = conn.execute(
                "SELECT 1 FROM notes WHERE category = ? AND filename = ?",
                (category, filename),
            ).fetchone()
        if existing:
            continue
        if filepath.name.lower() == "note.md":
            title = filepath.parent.name.replace("_", " ").title()
        else:
            title = filepath.stem.replace("_", " ").title()
        add_note(title=title, category=category, filename=filename, db_path=db_path)
        added += 1
    return added
