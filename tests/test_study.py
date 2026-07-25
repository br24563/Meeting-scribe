"""Flashcard parsing, spaced-repetition scheduling, and action-item storage."""
import engine


# ------------------------ parsing model output ------------------------

def test_parses_clean_q_a_pairs():
    raw = "Q: What is mitosis?\nA: Division producing two identical cells.\n\nQ: Define anaphase.\nA: Chromatids separate."
    cards = engine.parse_flashcards(raw)
    assert len(cards) == 2
    assert cards[0] == {"question": "What is mitosis?",
                        "answer": "Division producing two identical cells."}


def test_tolerates_preamble_numbering_and_markdown():
    """Models add chatter and formatting even when told not to."""
    raw = (
        "Sure! Here are your flashcards:\n\n"
        "1. Q: **What is a nucleophile?**\n"
        "   A: *An electron-rich species that donates a pair.*\n\n"
        "2) q: What is an electrophile?\n"
        "   a: Electron-poor; accepts a pair.\n\n"
        "Let me know if you'd like more!"
    )
    cards = engine.parse_flashcards(raw)
    assert len(cards) == 2
    assert cards[0]["question"] == "What is a nucleophile?"      # bold stripped
    assert cards[0]["answer"] == "An electron-rich species that donates a pair."
    assert cards[1]["question"] == "What is an electrophile?"    # lowercase q:/a:


def test_ignores_unpaired_or_empty_entries():
    assert engine.parse_flashcards("Q: Dangling question with no answer") == []
    assert engine.parse_flashcards("") == []
    assert engine.parse_flashcards(None) == []
    assert engine.parse_flashcards("Just prose, no cards here.") == []


# --------------------------- storing cards ----------------------------

def test_add_flashcards_skips_duplicate_questions(tmp_path):
    import db
    db_path = tmp_path / "cards.db"
    cards = [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]

    assert db.add_flashcards("Lectures", "n/note.md", cards, db_path=db_path) == 2
    # Regenerating shouldn't duplicate or reset progress
    assert db.add_flashcards("Lectures", "n/note.md", cards, db_path=db_path) == 0
    assert db.flashcard_stats(db_path=db_path)["total"] == 2


def test_add_flashcards_skips_incomplete_cards(tmp_path):
    import db
    db_path = tmp_path / "cards.db"
    cards = [{"question": "Good", "answer": "Yes"}, {"question": "", "answer": "orphan"},
             {"question": "No answer", "answer": "  "}]
    assert db.add_flashcards("Lectures", "n/note.md", cards, db_path=db_path) == 1


# ------------------------ spaced repetition ---------------------------

def _one_card(tmp_path, db):
    db_path = tmp_path / "sched.db"
    db.add_flashcards("Lectures", "n/note.md", [{"question": "Q", "answer": "A"}],
                      today="2026-03-01", db_path=db_path)
    return db_path, db.all_flashcards(db_path=db_path)[0]


def test_good_grade_grows_the_interval(tmp_path):
    import db
    db_path, card = _one_card(tmp_path, db)

    first = db.review_flashcard(card["id"], "good", today="2026-03-01", db_path=db_path)
    assert first["interval_days"] == 1
    assert first["due_at"] == "2026-03-02"
    assert first["reps"] == 1

    second = db.review_flashcard(card["id"], "good", today="2026-03-02", db_path=db_path)
    assert second["interval_days"] > first["interval_days"]  # 1 -> ~3 at ease 2.5
    assert second["due_at"] > first["due_at"]


def test_again_grade_reschedules_same_day_and_lowers_ease(tmp_path):
    import db
    db_path, card = _one_card(tmp_path, db)
    db.review_flashcard(card["id"], "good", today="2026-03-01", db_path=db_path)

    lapsed = db.review_flashcard(card["id"], "again", today="2026-03-02", db_path=db_path)
    assert lapsed["interval_days"] == 0
    assert lapsed["due_at"] == "2026-03-02"      # comes straight back
    assert lapsed["lapses"] == 1
    assert lapsed["ease"] < 2.5


def test_easy_grade_jumps_further_than_good(tmp_path):
    import db
    easy_path, easy_card = _one_card(tmp_path, db)
    easy = db.review_flashcard(easy_card["id"], "easy", today="2026-03-01", db_path=easy_path)

    good_path = tmp_path / "good.db"
    db.add_flashcards("Lectures", "n/note.md", [{"question": "Q", "answer": "A"}],
                      today="2026-03-01", db_path=good_path)
    good_card = db.all_flashcards(db_path=good_path)[0]
    good = db.review_flashcard(good_card["id"], "good", today="2026-03-01", db_path=good_path)

    assert easy["interval_days"] > good["interval_days"]
    assert easy["ease"] > good["ease"]


def test_ease_is_clamped_to_a_sane_range(tmp_path):
    import db
    db_path, card = _one_card(tmp_path, db)
    for _ in range(20):
        state = db.review_flashcard(card["id"], "again", today="2026-03-01", db_path=db_path)
    assert state["ease"] >= db.MIN_EASE

    for _ in range(20):
        state = db.review_flashcard(card["id"], "easy", today="2026-03-01", db_path=db_path)
    assert state["ease"] <= db.MAX_EASE


def test_interval_is_capped_so_due_dates_stay_representable(tmp_path):
    """Regression guard: intervals compound, and without a ceiling a card graded
    Easy repeatedly overflowed datetime.date and crashed the review session."""
    import db
    db_path, card = _one_card(tmp_path, db)
    for _ in range(40):
        state = db.review_flashcard(card["id"], "easy", today="2026-03-01", db_path=db_path)
    assert state["interval_days"] == db.MAX_INTERVAL_DAYS
    assert state["due_at"] > "2026-03-01"  # a real date, not an exception


def test_due_filtering_respects_the_schedule(tmp_path):
    import db
    db_path, card = _one_card(tmp_path, db)
    assert len(db.due_flashcards(today="2026-03-01", db_path=db_path)) == 1

    db.review_flashcard(card["id"], "good", today="2026-03-01", db_path=db_path)
    assert db.due_flashcards(today="2026-03-01", db_path=db_path) == []   # pushed to tomorrow
    assert len(db.due_flashcards(today="2026-03-02", db_path=db_path)) == 1


def test_reviewing_a_missing_card_returns_none(tmp_path):
    import db
    db_path = tmp_path / "empty.db"
    assert db.review_flashcard(999, "good", db_path=db_path) is None


# --------------------- action item persistence ------------------------

def test_replace_action_items_resyncs_from_the_note(tmp_path):
    import db
    db_path = tmp_path / "tasks.db"
    first_pass = engine.parse_action_items("- [ ] One\n- [ ] Two\n")
    db.replace_action_items("Meetings", "m/note.md", first_pass, db_path=db_path)
    assert db.action_item_stats(db_path=db_path) == {"total": 2, "done": 0, "open": 2}

    # The note was edited: one task ticked, one removed, one added
    second_pass = engine.parse_action_items("- [x] One\n- [ ] Three\n")
    db.replace_action_items("Meetings", "m/note.md", second_pass, db_path=db_path)
    stats = db.action_item_stats(db_path=db_path)
    assert stats == {"total": 2, "done": 1, "open": 1}
    assert {i["text"] for i in db.action_items(include_done=True, db_path=db_path)} == {"One", "Three"}


def test_action_items_hides_completed_by_default(tmp_path):
    import db
    db_path = tmp_path / "tasks.db"
    db.replace_action_items("Meetings", "m/note.md",
                            engine.parse_action_items("- [x] Done\n- [ ] Open\n"), db_path=db_path)
    assert [i["text"] for i in db.action_items(db_path=db_path)] == ["Open"]
    assert len(db.action_items(include_done=True, db_path=db_path)) == 2


def test_set_action_done_updates_state_and_stored_line(tmp_path):
    import db
    db_path = tmp_path / "tasks.db"
    db.replace_action_items("Meetings", "m/note.md",
                            engine.parse_action_items("- [ ] Ship it\n"), db_path=db_path)
    item = db.action_items(db_path=db_path)[0]

    db.set_action_done(item["id"], True, new_raw_line="- [x] Ship it", db_path=db_path)
    updated = db.get_action_item(item["id"], db_path=db_path)
    assert updated["done"] == 1
    assert updated["raw_line"] == "- [x] Ship it"


# ------------------- cascade behaviour on notes -----------------------

def test_deleting_a_note_can_take_its_cards_and_tasks(tmp_path):
    import db
    db_path = tmp_path / "cascade.db"
    db.add_note("N", "Lectures", "n/note.md", db_path=db_path)
    db.add_flashcards("Lectures", "n/note.md", [{"question": "Q", "answer": "A"}], db_path=db_path)
    db.replace_action_items("Lectures", "n/note.md",
                            engine.parse_action_items("- [ ] T\n"), db_path=db_path)

    db.delete_note("Lectures", "n/note.md", cascade=True, db_path=db_path)
    assert db.flashcard_stats(db_path=db_path)["total"] == 0
    assert db.action_item_stats(db_path=db_path)["total"] == 0


def test_pruning_a_temporarily_missing_note_keeps_review_history(tmp_path):
    """prune_missing() runs when a cloud folder may simply not have synced yet —
    it must not be able to destroy someone's flashcard progress."""
    import db
    db_path = tmp_path / "cascade.db"
    db.add_note("N", "Lectures", "n/note.md", db_path=db_path)
    db.add_flashcards("Lectures", "n/note.md", [{"question": "Q", "answer": "A"}], db_path=db_path)

    db.prune_missing(storage_dir=tmp_path / "nothing_here", db_path=db_path)

    assert db.recent_notes(db_path=db_path) == []          # note un-indexed...
    assert db.flashcard_stats(db_path=db_path)["total"] == 1  # ...but cards survive


def test_renaming_a_note_keeps_its_cards_and_tasks_attached(tmp_path):
    import db
    db_path = tmp_path / "rename.db"
    db.add_note("Old", "Lectures", "old/note.md", db_path=db_path)
    db.add_flashcards("Lectures", "old/note.md", [{"question": "Q", "answer": "A"}], db_path=db_path)
    db.replace_action_items("Lectures", "old/note.md",
                            engine.parse_action_items("- [ ] T\n"), db_path=db_path)

    db.rename_note("Lectures", "old/note.md", "new/note.md", "New", db_path=db_path)

    assert db.all_flashcards(db_path=db_path)[0]["filename"] == "new/note.md"
    assert db.action_items(db_path=db_path)[0]["filename"] == "new/note.md"
