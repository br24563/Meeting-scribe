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
import uuid
from datetime import date, datetime, timedelta, timezone
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

CREATE TABLE IF NOT EXISTS flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    due_at TEXT NOT NULL,
    interval_days INTEGER NOT NULL DEFAULT 0,
    ease REAL NOT NULL DEFAULT 2.5,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, filename, question)
);
CREATE INDEX IF NOT EXISTS idx_flashcards_due ON flashcards(due_at);

CREATE TABLE IF NOT EXISTS lms_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL UNIQUE,
    last_synced TEXT,
    last_status TEXT DEFAULT '',
    event_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deadlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    uid TEXT NOT NULL,
    title TEXT NOT NULL,
    course TEXT DEFAULT '',
    due_at TEXT NOT NULL,
    all_day INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'assignment',
    url TEXT DEFAULT '',
    description TEXT DEFAULT '',
    completed INTEGER NOT NULL DEFAULT 0,
    -- Set when the student edits a deadline that came from a feed. Syncing then
    -- leaves their version alone instead of overwriting it, while feed_title /
    -- feed_due_at keep the LMS's own values so "reset to the LMS version" works.
    user_edited INTEGER NOT NULL DEFAULT 0,
    feed_title TEXT DEFAULT '',
    feed_due_at TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_deadlines_due ON deadlines(due_at);
CREATE INDEX IF NOT EXISTS idx_deadlines_completed ON deadlines(completed);

CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    text TEXT NOT NULL,
    owner TEXT DEFAULT '',
    due TEXT DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    raw_line TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, filename, raw_line)
);
CREATE INDEX IF NOT EXISTS idx_action_items_done ON action_items(done);
"""

# Bind-variable batch size for generated IN(…) clauses. Comfortably under the
# 999-variable cap of SQLite builds older than 3.32.
_SQL_CHUNK = 500

# Spaced repetition, SM-2 without the parts that need a full review history.
MIN_EASE, MAX_EASE = 1.3, 3.0
# Ten years. Intervals compound, so without a ceiling a well-known card can be
# pushed past the range `datetime.date` can represent, crashing the review.
MAX_INTERVAL_DAYS = 3650

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


def delete_note(category: str, filename: str, cascade: bool = False, db_path=None) -> None:
    """Remove a note from the index.

    `cascade` also drops its flashcards and action items, and is used when the
    user deletes a note outright. It stays off for prune_missing(), where a
    note may only be *temporarily* absent — a cloud folder that hasn't finished
    syncing shouldn't cost someone their review history.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM notes WHERE category = ? AND filename = ?",
            (category, filename),
        )
        if cascade:
            conn.execute("DELETE FROM flashcards WHERE category = ? AND filename = ?",
                         (category, filename))
            conn.execute("DELETE FROM action_items WHERE category = ? AND filename = ?",
                         (category, filename))


def rename_note(category: str, old_filename: str, new_filename: str, new_title: str,
                db_path=None) -> None:
    """Rename a note and re-point everything keyed to it, so a rename never
    orphans its flashcards or action items."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE notes SET filename = ?, title = ? WHERE category = ? AND filename = ?",
            (new_filename, new_title, category, old_filename),
        )
        for table in ("flashcards", "action_items"):
            conn.execute(
                f"UPDATE OR IGNORE {table} SET filename = ? WHERE category = ? AND filename = ?",
                (new_filename, category, old_filename),
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


# ---------------------------------------------------------------------------
# Flashcards (student study mode)
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _add_days(iso_day: str, days: int) -> str:
    return (date.fromisoformat(iso_day) + timedelta(days=max(0, int(days)))).isoformat()


def add_flashcards(category: str, filename: str, cards, today: str = None, db_path=None) -> int:
    """Store generated cards, skipping questions already saved for this note so
    regenerating doesn't create duplicates or reset review progress."""
    today = today or _today()
    added = 0
    with _connect(db_path) as conn:
        for card in cards:
            question = (card.get("question") or "").strip()
            answer = (card.get("answer") or "").strip()
            if not question or not answer:
                continue
            cursor = conn.execute(
                """INSERT OR IGNORE INTO flashcards
                   (category, filename, question, answer, due_at) VALUES (?, ?, ?, ?, ?)""",
                (category, filename, question, answer, today),
            )
            added += cursor.rowcount or 0
    return added


def due_flashcards(today: str = None, limit: int = 50, category: str = None, db_path=None):
    """Cards ready for review, soonest-due first."""
    today = today or _today()
    sql = "SELECT * FROM flashcards WHERE due_at <= ?"
    params = [today]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY due_at, id LIMIT ?"
    params.append(limit)
    with _connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def all_flashcards(category: str = None, db_path=None):
    sql = "SELECT * FROM flashcards"
    params = []
    if category:
        sql += " WHERE category = ?"
        params.append(category)
    sql += " ORDER BY category, filename, id"
    with _connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def flashcard_stats(today: str = None, db_path=None):
    today = today or _today()
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM flashcards").fetchone()["n"]
        due = conn.execute(
            "SELECT COUNT(*) AS n FROM flashcards WHERE due_at <= ?", (today,)
        ).fetchone()["n"]
        reviewed = conn.execute(
            "SELECT COUNT(*) AS n FROM flashcards WHERE reps > 0"
        ).fetchone()["n"]
    return {"total": total, "due": due, "reviewed": reviewed}


def review_flashcard(card_id: int, grade: str, today: str = None, db_path=None):
    """Record a review and reschedule the card.

    `grade` is "again", "good", or "easy". Intervals grow by the card's ease
    factor; "again" resets it to same-day and nudges the ease down, so cards
    you keep missing keep coming back.
    """
    today = today or _today()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        ease, interval = row["ease"], row["interval_days"]
        reps, lapses = row["reps"] + 1, row["lapses"]

        if grade == "again":
            ease = max(MIN_EASE, ease - 0.20)
            interval = 0
            lapses += 1
        elif grade == "easy":
            ease = min(MAX_EASE, ease + 0.15)
            interval = min(MAX_INTERVAL_DAYS, max(4, round(max(interval, 1) * ease * 1.3)))
        else:  # "good"
            interval = 1 if interval < 1 else min(MAX_INTERVAL_DAYS, max(1, round(interval * ease)))

        due_at = _add_days(today, interval)
        conn.execute(
            """UPDATE flashcards SET ease = ?, interval_days = ?, reps = ?, lapses = ?, due_at = ?
               WHERE id = ?""",
            (ease, interval, reps, lapses, due_at, card_id),
        )
    return {"id": card_id, "ease": ease, "interval_days": interval, "reps": reps,
            "lapses": lapses, "due_at": due_at}


def delete_flashcards_for_note(category: str, filename: str, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM flashcards WHERE category = ? AND filename = ?",
                     (category, filename))


# ---------------------------------------------------------------------------
# Action items (professional task tracking)
# ---------------------------------------------------------------------------

def replace_action_items(category: str, filename: str, items, db_path=None) -> int:
    """Re-sync a note's action items with what its Markdown currently says.

    The note file is the source of truth for both the wording and the tick
    state, so a rescan replaces the rows outright rather than trying to merge —
    which keeps the app and the file from drifting apart.
    """
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM action_items WHERE category = ? AND filename = ?",
                     (category, filename))
        stored = 0
        for item in items:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO action_items
                   (category, filename, text, owner, due, done, raw_line)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (category, filename, item["text"], item.get("owner", ""),
                 item.get("due", ""), 1 if item.get("done") else 0, item["raw_line"]),
            )
            stored += cursor.rowcount or 0
    return stored


def action_items(category: str = None, include_done: bool = False, db_path=None):
    sql = "SELECT * FROM action_items WHERE 1=1"
    params = []
    if not include_done:
        sql += " AND done = 0"
    if category:
        sql += " AND category = ?"
        params.append(category)
    # Items with a stated due date first, then by note
    sql += " ORDER BY done, (due = '') , due, category, filename, id"
    with _connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_action_item(item_id: int, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM action_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def set_action_done(item_id: int, done: bool, new_raw_line: str = None, db_path=None) -> None:
    """Mark an item complete. `new_raw_line` keeps the stored line in step with
    the rewritten Markdown, so a later rescan matches it."""
    with _connect(db_path) as conn:
        if new_raw_line is None:
            conn.execute("UPDATE action_items SET done = ? WHERE id = ?",
                         (1 if done else 0, item_id))
        else:
            conn.execute("UPDATE action_items SET done = ?, raw_line = ? WHERE id = ?",
                         (1 if done else 0, new_raw_line, item_id))


def action_item_stats(db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(done), 0) AS done FROM action_items"
        ).fetchone()
    total, done = row["total"], int(row["done"] or 0)
    return {"total": total, "done": done, "open": total - done}


def delete_action_items_for_note(category: str, filename: str, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM action_items WHERE category = ? AND filename = ?",
                     (category, filename))


# ---------------------------------------------------------------------------
# LMS calendar feeds and the deadlines they contain
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def add_lms_source(name: str, provider: str, url: str, db_path=None) -> int:
    """Register a calendar feed, or return the existing row if the URL is
    already connected (so pasting the same link twice doesn't duplicate it)."""
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO lms_sources (name, provider, url) VALUES (?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET name = excluded.name,
                                              provider = excluded.provider""",
            (name, provider, url),
        )
        row = conn.execute("SELECT id FROM lms_sources WHERE url = ?", (url,)).fetchone()
    return row["id"]


def lms_sources(db_path=None):
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM lms_sources ORDER BY name, id").fetchall()
    return [dict(row) for row in rows]


def get_lms_source(source_id: int, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM lms_sources WHERE id = ?", (source_id,)).fetchone()
    return dict(row) if row else None


def update_lms_source_status(source_id: int, status: str, event_count: int = None,
                             synced_at: str = None, db_path=None) -> None:
    with _connect(db_path) as conn:
        if event_count is None:
            conn.execute("UPDATE lms_sources SET last_status = ?, last_synced = ? WHERE id = ?",
                         (status, synced_at or _utc_now_iso(), source_id))
        else:
            conn.execute(
                """UPDATE lms_sources SET last_status = ?, last_synced = ?, event_count = ?
                   WHERE id = ?""",
                (status, synced_at or _utc_now_iso(), event_count, source_id),
            )


def delete_lms_source(source_id: int, db_path=None) -> None:
    """Disconnect a feed and drop the deadlines that came from it. Manually
    added deadlines have no source and are untouched."""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM deadlines WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM lms_sources WHERE id = ?", (source_id,))


def upsert_deadlines(source_id: int, items, db_path=None):
    """Sync a feed's deadlines into the index.

    Existing rows are updated in place — a professor moving a due date should be
    reflected — with two deliberate exceptions:

    * the student's `completed` tick is never cleared, so re-syncing can't
      un-finish their work; and
    * a row they've edited themselves keeps their version. The feed's own values
      are still recorded in feed_title/feed_due_at so the edit can be reverted.

    Returns (added, updated, skipped_edited).
    """
    added = updated = skipped = 0
    with _connect(db_path) as conn:
        for item in items:
            existing = conn.execute(
                "SELECT id, user_edited FROM deadlines WHERE source_id IS ? AND uid = ?",
                (source_id, item["uid"]),
            ).fetchone()
            if existing and existing["user_edited"]:
                # Track what the feed says now, but leave the student's edit intact.
                conn.execute(
                    "UPDATE deadlines SET feed_title = ?, feed_due_at = ? WHERE id = ?",
                    (item["title"], item["due_at"], existing["id"]),
                )
                skipped += 1
            elif existing:
                conn.execute(
                    """UPDATE deadlines SET title = ?, course = ?, due_at = ?, all_day = ?,
                              kind = ?, url = ?, description = ?,
                              feed_title = ?, feed_due_at = ? WHERE id = ?""",
                    (item["title"], item.get("course", ""), item["due_at"],
                     1 if item.get("all_day") else 0, item.get("kind", "assignment"),
                     item.get("url", ""), item.get("description", ""),
                     item["title"], item["due_at"], existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO deadlines
                       (source_id, uid, title, course, due_at, all_day, kind, url,
                        description, feed_title, feed_due_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source_id, item["uid"], item["title"], item.get("course", ""),
                     item["due_at"], 1 if item.get("all_day") else 0,
                     item.get("kind", "assignment"), item.get("url", ""),
                     item.get("description", ""), item["title"], item["due_at"]),
                )
                added += 1
    return added, updated, skipped


def update_deadline(deadline_id: int, title: str = None, course: str = None,
                    due_at: str = None, all_day: bool = None, kind: str = None,
                    url: str = None, description: str = None,
                    mark_edited: bool = True, db_path=None) -> None:
    """Edit a deadline. Any field left as None is untouched.

    Editing a feed-sourced deadline marks it as user-edited so the next sync
    respects the change rather than overwriting it.
    """
    fields, values = [], []
    for column, value in (("title", title), ("course", course), ("due_at", due_at),
                          ("kind", kind), ("url", url), ("description", description)):
        if value is not None:
            fields.append(f"{column} = ?")
            values.append(value)
    if all_day is not None:
        fields.append("all_day = ?")
        values.append(1 if all_day else 0)
    if not fields:
        return
    if mark_edited:
        fields.append("user_edited = 1")
    values.append(deadline_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE deadlines SET {', '.join(fields)} WHERE id = ?", values)


def revert_deadline_to_feed(deadline_id: int, db_path=None) -> bool:
    """Discard a local edit and go back to what the LMS feed says.

    Returns False when there's nothing to revert to (a manually added deadline,
    or one whose feed values were never recorded).
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT feed_title, feed_due_at FROM deadlines WHERE id = ?", (deadline_id,)
        ).fetchone()
        if row is None or not row["feed_title"] or not row["feed_due_at"]:
            return False
        conn.execute(
            """UPDATE deadlines SET title = ?, due_at = ?, user_edited = 0 WHERE id = ?""",
            (row["feed_title"], row["feed_due_at"], deadline_id),
        )
    return True


def prune_deadlines_missing_from_feed(source_id: int, seen_uids, db_path=None) -> int:
    """Drop rows for a feed's entries that no longer appear in it — an assignment
    the professor deleted.

    Skipped entirely when the feed returned nothing, so a partial fetch can't
    wipe a term's deadlines, and rows the student has edited are always kept:
    their own work outranks the feed's idea of what exists.

    The difference is computed in Python rather than with a `uid NOT IN (…)`
    list: a year of a busy calendar (recurring lectures especially) runs to
    thousands of entries, and SQLite builds older than 3.32 cap a statement at
    999 variables — which would have made syncing fail outright for exactly the
    students with the most to keep track of.
    """
    seen = set(seen_uids)
    if not seen:
        return 0

    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, uid FROM deadlines WHERE source_id IS ? AND user_edited = 0",
            (source_id,),
        ).fetchall()
        stale = [row["id"] for row in rows if row["uid"] not in seen]
        for start in range(0, len(stale), _SQL_CHUNK):
            chunk = stale[start:start + _SQL_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM deadlines WHERE id IN ({placeholders})", chunk)
    return len(stale)


def add_manual_deadline(title: str, due_at: str, course: str = "", all_day: bool = False,
                        kind: str = "assignment", url: str = "", description: str = "",
                        db_path=None) -> int:
    """Add a deadline by hand — for a Gradescope-only assignment, or anything
    that isn't in a feed. Stored with no source so syncing never disturbs it."""
    uid = f"manual-{uuid.uuid4().hex[:16]}"
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO deadlines
               (source_id, uid, title, course, due_at, all_day, kind, url, description)
               VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, title, course, due_at, 1 if all_day else 0, kind, url, description),
        )
        return cursor.lastrowid


def deadlines(include_completed: bool = False, since: str = None, until: str = None,
              db_path=None):
    sql = "SELECT * FROM deadlines WHERE 1=1"
    params = []
    if not include_completed:
        sql += " AND completed = 0"
    if since:
        sql += " AND due_at >= ?"
        params.append(since)
    if until:
        sql += " AND due_at <= ?"
        params.append(until)
    sql += " ORDER BY due_at, title"
    with _connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def overdue_deadlines(now: str = None, db_path=None):
    """Open deadlines whose date has passed."""
    now = now or _utc_now_iso()
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM deadlines WHERE completed = 0 AND due_at < ? ORDER BY due_at",
            (now,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_deadline_completed(deadline_id: int, completed: bool, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE deadlines SET completed = ? WHERE id = ?",
                     (1 if completed else 0, deadline_id))


def delete_deadline(deadline_id: int, db_path=None) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM deadlines WHERE id = ?", (deadline_id,))


def deadline_stats(now: str = None, horizon_days: int = 7, db_path=None):
    now = now or _utc_now_iso()
    horizon = (datetime.fromisoformat(now) + timedelta(days=horizon_days)) \
        .replace(microsecond=0).isoformat()
    with _connect(db_path) as conn:
        overdue = conn.execute(
            "SELECT COUNT(*) AS n FROM deadlines WHERE completed = 0 AND due_at < ?", (now,)
        ).fetchone()["n"]
        soon = conn.execute(
            """SELECT COUNT(*) AS n FROM deadlines
               WHERE completed = 0 AND due_at >= ? AND due_at <= ?""", (now, horizon)
        ).fetchone()["n"]
        total_open = conn.execute(
            "SELECT COUNT(*) AS n FROM deadlines WHERE completed = 0"
        ).fetchone()["n"]
    return {"overdue": overdue, "due_soon": soon, "open": total_open}


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
