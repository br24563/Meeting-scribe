"""Deadline storage: syncing, editing, and the interaction between the two."""
import db


def feed_item(uid, title="Problem Set 1", due="2026-09-01T23:59:00+00:00", **extra):
    item = {"uid": uid, "title": title, "due_at": due, "course": "BIO 201",
            "all_day": False, "kind": "assignment", "url": "", "description": ""}
    item.update(extra)
    return item


def _source(tmp_path, db_path):
    return db.add_lms_source("Canvas", "Canvas", "https://school.edu/f.ics", db_path=db_path)


# ------------------------------- sources ----------------------------------

def test_add_source_is_idempotent_per_url(tmp_path):
    db_path = tmp_path / "d.db"
    first = db.add_lms_source("Canvas", "Canvas", "https://school.edu/f.ics", db_path=db_path)
    second = db.add_lms_source("Renamed", "Canvas", "https://school.edu/f.ics", db_path=db_path)
    assert first == second                                  # same feed, not a duplicate
    assert len(db.lms_sources(db_path=db_path)) == 1
    assert db.get_lms_source(first, db_path=db_path)["name"] == "Renamed"


def test_deleting_a_source_removes_its_deadlines_but_not_manual_ones(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a")], db_path=db_path)
    db.add_manual_deadline("Gradescope PS2", "2026-09-05T23:59:00+00:00", db_path=db_path)

    db.delete_lms_source(source, db_path=db_path)

    remaining = db.deadlines(db_path=db_path)
    assert [d["title"] for d in remaining] == ["Gradescope PS2"]
    assert db.lms_sources(db_path=db_path) == []


def test_source_status_is_recorded(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.update_lms_source_status(source, "ok", event_count=12, synced_at="2026-07-01T10:00:00+00:00",
                                db_path=db_path)
    row = db.get_lms_source(source, db_path=db_path)
    assert (row["last_status"], row["event_count"]) == ("ok", 12)
    assert row["last_synced"] == "2026-07-01T10:00:00+00:00"


# -------------------------------- syncing ---------------------------------

def test_upsert_adds_then_updates_without_duplicating(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)

    assert db.upsert_deadlines(source, [feed_item("a")], db_path=db_path) == (1, 0, 0)
    # The professor moves the due date
    moved = feed_item("a", title="Problem Set 1 (revised)", due="2026-09-08T23:59:00+00:00")
    assert db.upsert_deadlines(source, [moved], db_path=db_path) == (0, 1, 0)

    rows = db.deadlines(db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["title"] == "Problem Set 1 (revised)"
    assert rows[0]["due_at"] == "2026-09-08T23:59:00+00:00"


def test_resync_never_unticks_completed_work(tmp_path):
    """The whole point of the upsert: finishing something then re-syncing must
    not mark it unfinished again."""
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a")], db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    db.set_deadline_completed(row["id"], True, db_path=db_path)

    db.upsert_deadlines(source, [feed_item("a", title="Problem Set 1 v2")], db_path=db_path)

    assert db.deadlines(db_path=db_path) == []              # still hidden as done
    still_done = db.deadlines(include_completed=True, db_path=db_path)[0]
    assert still_done["completed"] == 1
    assert still_done["title"] == "Problem Set 1 v2"        # but the text did update


def test_prune_removes_deleted_assignments(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a"), feed_item("b", title="PS2")], db_path=db_path)

    removed = db.prune_deadlines_missing_from_feed(source, ["a"], db_path=db_path)

    assert removed == 1
    assert [d["uid"] for d in db.deadlines(db_path=db_path)] == ["a"]


def test_prune_does_nothing_when_the_feed_came_back_empty(tmp_path):
    """A partial or failed fetch must never wipe a term's deadlines."""
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a"), feed_item("b")], db_path=db_path)

    assert db.prune_deadlines_missing_from_feed(source, [], db_path=db_path) == 0
    assert len(db.deadlines(db_path=db_path)) == 2


def test_manual_deadlines_are_untouched_by_syncing(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.add_manual_deadline("Gradescope-only PS3", "2026-09-10T23:59:00+00:00", db_path=db_path)

    db.upsert_deadlines(source, [feed_item("a")], db_path=db_path)
    db.prune_deadlines_missing_from_feed(source, ["a"], db_path=db_path)

    titles = {d["title"] for d in db.deadlines(db_path=db_path)}
    assert "Gradescope-only PS3" in titles


# -------------------------------- editing ---------------------------------

def test_editing_a_deadline_changes_it_and_flags_it(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a")], db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]

    db.update_deadline(row["id"], title="PS1 — my version",
                       due_at="2026-08-30T18:00:00+00:00",
                       description="Prof said focus on Q3", db_path=db_path)

    edited = db.deadlines(db_path=db_path)[0]
    assert edited["title"] == "PS1 — my version"
    assert edited["due_at"] == "2026-08-30T18:00:00+00:00"
    assert edited["description"] == "Prof said focus on Q3"
    assert edited["user_edited"] == 1


def test_editing_only_the_named_fields(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Original", "2026-09-01T12:00:00+00:00", course="CS 1",
                           db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]

    db.update_deadline(row["id"], title="Renamed", db_path=db_path)

    updated = db.deadlines(db_path=db_path)[0]
    assert updated["title"] == "Renamed"
    assert updated["course"] == "CS 1"                      # untouched
    assert updated["due_at"] == "2026-09-01T12:00:00+00:00"  # untouched


def test_update_with_no_fields_is_a_noop(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Thing", "2026-09-01T12:00:00+00:00", db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    db.update_deadline(row["id"], db_path=db_path)
    assert db.deadlines(db_path=db_path)[0]["user_edited"] == 0


def test_sync_respects_a_users_edit_instead_of_overwriting_it(tmp_path):
    """The important one: editing an LMS deadline then re-syncing must keep the
    student's version rather than silently reverting their change."""
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a")], db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    db.update_deadline(row["id"], title="Start this early!",
                       due_at="2026-08-28T09:00:00+00:00", db_path=db_path)

    added, updated, skipped = db.upsert_deadlines(
        source, [feed_item("a", title="Problem Set 1", due="2026-09-01T23:59:00+00:00")],
        db_path=db_path)

    assert (added, updated, skipped) == (0, 0, 1)
    kept = db.deadlines(db_path=db_path)[0]
    assert kept["title"] == "Start this early!"
    assert kept["due_at"] == "2026-08-28T09:00:00+00:00"
    # ...while still tracking what the feed currently says
    assert kept["feed_title"] == "Problem Set 1"
    assert kept["feed_due_at"] == "2026-09-01T23:59:00+00:00"


def test_reverting_an_edit_restores_the_feed_version(tmp_path):
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a")], db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    db.update_deadline(row["id"], title="Mine", due_at="2026-08-01T00:00:00+00:00",
                       db_path=db_path)

    assert db.revert_deadline_to_feed(row["id"], db_path=db_path) is True

    restored = db.deadlines(db_path=db_path)[0]
    assert restored["title"] == "Problem Set 1"
    assert restored["due_at"] == "2026-09-01T23:59:00+00:00"
    assert restored["user_edited"] == 0


def test_reverting_a_manual_deadline_reports_nothing_to_revert_to(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Hand-made", "2026-09-01T12:00:00+00:00", db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    assert db.revert_deadline_to_feed(row["id"], db_path=db_path) is False
    assert db.deadlines(db_path=db_path)[0]["title"] == "Hand-made"


def test_prune_keeps_a_deadline_the_student_has_edited(tmp_path):
    """If they've put work into it, a feed dropping the entry shouldn't bin it."""
    db_path = tmp_path / "d.db"
    source = _source(tmp_path, db_path)
    db.upsert_deadlines(source, [feed_item("a"), feed_item("b", title="PS2")], db_path=db_path)
    edited = next(d for d in db.deadlines(db_path=db_path) if d["uid"] == "b")
    db.update_deadline(edited["id"], title="PS2 (rescheduled by email)", db_path=db_path)

    db.prune_deadlines_missing_from_feed(source, ["a"], db_path=db_path)

    titles = {d["title"] for d in db.deadlines(db_path=db_path)}
    assert "PS2 (rescheduled by email)" in titles


def test_deleting_a_deadline_removes_it(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Scrap this", "2026-09-01T12:00:00+00:00", db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    db.delete_deadline(row["id"], db_path=db_path)
    assert db.deadlines(db_path=db_path) == []


# ------------------------- queries and statistics -------------------------

def test_overdue_and_upcoming_are_separated(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Late thing", "2026-06-01T12:00:00+00:00", db_path=db_path)
    db.add_manual_deadline("Soon thing", "2026-07-03T12:00:00+00:00", db_path=db_path)
    db.add_manual_deadline("Far thing", "2026-12-01T12:00:00+00:00", db_path=db_path)
    now = "2026-07-01T00:00:00+00:00"

    assert [d["title"] for d in db.overdue_deadlines(now=now, db_path=db_path)] == ["Late thing"]

    stats = db.deadline_stats(now=now, horizon_days=7, db_path=db_path)
    assert stats == {"overdue": 1, "due_soon": 1, "open": 3}


def test_completed_deadlines_drop_out_of_stats_and_lists(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Done early", "2026-07-03T12:00:00+00:00", db_path=db_path)
    row = db.deadlines(db_path=db_path)[0]
    db.set_deadline_completed(row["id"], True, db_path=db_path)

    now = "2026-07-01T00:00:00+00:00"
    assert db.deadline_stats(now=now, db_path=db_path)["due_soon"] == 0
    assert db.deadlines(db_path=db_path) == []
    assert len(db.deadlines(include_completed=True, db_path=db_path)) == 1

    db.set_deadline_completed(row["id"], False, db_path=db_path)
    assert len(db.deadlines(db_path=db_path)) == 1          # and can be reopened


def test_deadlines_can_be_filtered_to_a_window(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Inside", "2026-07-05T12:00:00+00:00", db_path=db_path)
    db.add_manual_deadline("Outside", "2026-09-05T12:00:00+00:00", db_path=db_path)

    found = db.deadlines(since="2026-07-01T00:00:00+00:00",
                         until="2026-07-31T00:00:00+00:00", db_path=db_path)
    assert [d["title"] for d in found] == ["Inside"]


def test_deadlines_are_returned_in_due_order(tmp_path):
    db_path = tmp_path / "d.db"
    db.add_manual_deadline("Third", "2026-09-03T12:00:00+00:00", db_path=db_path)
    db.add_manual_deadline("First", "2026-09-01T12:00:00+00:00", db_path=db_path)
    db.add_manual_deadline("Second", "2026-09-02T12:00:00+00:00", db_path=db_path)
    assert [d["title"] for d in db.deadlines(db_path=db_path)] == ["First", "Second", "Third"]
