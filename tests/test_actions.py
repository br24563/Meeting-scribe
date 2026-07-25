"""Action items parsed out of note Markdown, and completions written back."""
import engine

TEMPLATE_STYLE_NOTE = """# Weekly Sync
*Category: Meetings*

> 💡 **Status in One Line**
> On track.

---
### 📋 Action Items
- [ ] **Send the revised deck** — Assigned to: Priya — Due: Friday
- [x] **Book the room** — Assigned to: Sam — Due: 2026-08-01
- [ ] Chase the vendor quote
* [ ] **Draft the summary** — Assigned to: Self

---
### 🏷️ Relevant Tags
#standup #team
"""


def test_parses_owner_due_and_done_state():
    items = engine.parse_action_items(TEMPLATE_STYLE_NOTE)
    assert len(items) == 4

    first = items[0]
    assert first["text"] == "Send the revised deck"   # metadata stripped from the text
    assert first["owner"] == "Priya"
    assert first["due"] == "Friday"
    assert first["done"] is False

    assert items[1]["done"] is True                    # [x] recognised
    assert items[1]["owner"] == "Sam"
    assert items[1]["due"] == "2026-08-01"

    assert items[2]["text"] == "Chase the vendor quote"  # bare task, no metadata
    assert items[2]["owner"] == "" and items[2]["due"] == ""

    assert items[3]["text"] == "Draft the summary"      # '*' bullet, owner only
    assert items[3]["owner"] == "Self"


def test_raw_line_is_preserved_verbatim_for_write_back():
    items = engine.parse_action_items(TEMPLATE_STYLE_NOTE)
    for item in items:
        assert item["raw_line"] in TEMPLATE_STYLE_NOTE


def test_parses_plain_hyphen_separators():
    """Regression guard: an end-to-end run against a real model showed it emits
    plain hyphens, not em dashes — which left the metadata glued to the task
    text and made `owner` swallow the due date."""
    note = "- [ ] **Send revised scope doc** - Assigned to: Priya - Due: Friday\n"
    items = engine.parse_action_items(note)
    assert len(items) == 1
    assert items[0]["text"] == "Send revised scope doc"
    assert items[0]["owner"] == "Priya"
    assert items[0]["due"] == "Friday"


def test_hyphenated_due_date_is_not_split_apart():
    """The separator is a dash surrounded by spaces, so the hyphens inside an
    ISO date must survive."""
    note = "- [ ] Book the room - Assigned to: Sam - Due: 2026-08-01\n"
    item = engine.parse_action_items(note)[0]
    assert item["due"] == "2026-08-01"
    assert item["owner"] == "Sam"
    assert item["text"] == "Book the room"


def test_parses_en_dash_and_pipe_separators():
    for line in (
        "- [ ] Ship the deck – Assigned to: Ana – Due: Monday",
        "- [ ] Ship the deck | Assigned to: Ana | Due: Monday",
    ):
        item = engine.parse_action_items(line + "\n")[0]
        assert item["text"] == "Ship the deck"
        assert item["owner"] == "Ana"
        assert item["due"] == "Monday"


def test_parses_metadata_with_no_separator():
    item = engine.parse_action_items("- [ ] Chase the quote Due: Friday\n")[0]
    assert item["text"] == "Chase the quote"
    assert item["due"] == "Friday"


def test_accepts_owner_as_a_field_name():
    item = engine.parse_action_items("- [ ] Review PR — Owner: Dev — Due: today\n")[0]
    assert item["owner"] == "Dev"
    assert item["text"] == "Review PR"


def test_task_text_keeps_internal_hyphens():
    item = engine.parse_action_items("- [ ] Draft the go-to-market one-pager\n")[0]
    assert item["text"] == "Draft the go-to-market one-pager"


def test_ignores_unfilled_template_placeholders():
    # A template the model left untouched should not become a real task
    note = "- [ ] **[Task 1]** — Assigned to: [Name/Role] — Due: [Date if mentioned]\n"
    assert engine.parse_action_items(note) == []


def test_placeholder_owner_and_due_are_dropped_but_real_task_kept():
    note = "- [ ] Email the professor — Assigned to: [Name/Role] — Due: [Date if mentioned]\n"
    items = engine.parse_action_items(note)
    assert len(items) == 1
    assert items[0]["text"] == "Email the professor"
    assert items[0]["owner"] == "" and items[0]["due"] == ""


def test_ignores_non_checkbox_lines():
    note = (
        "# Heading\n"
        "* A normal bullet\n"
        "- Another bullet\n"
        "Some prose with [brackets] in it.\n"
        "1. A numbered item\n"
    )
    assert engine.parse_action_items(note) == []


def test_handles_indented_and_uppercase_checkboxes():
    note = "  - [X] Nested done task\n    * [ ] Nested open task\n"
    items = engine.parse_action_items(note)
    assert [i["done"] for i in items] == [True, False]
    assert items[1]["text"] == "Nested open task"


def test_empty_and_none_input_are_safe():
    assert engine.parse_action_items("") == []
    assert engine.parse_action_items(None) == []


# ----------------------------- write-back -----------------------------

def test_set_checkbox_ticks_only_the_matching_line():
    items = engine.parse_action_items(TEMPLATE_STYLE_NOTE)
    target = items[0]
    updated, changed = engine.set_checkbox(TEMPLATE_STYLE_NOTE, target["raw_line"], True)

    assert changed is True
    assert "- [x] **Send the revised deck** — Assigned to: Priya — Due: Friday" in updated
    # The other open items are untouched
    assert "- [ ] Chase the vendor quote" in updated
    assert updated.count("[x]") == 2  # the newly ticked one plus the already-done one


def test_set_checkbox_can_reopen_a_done_item():
    items = engine.parse_action_items(TEMPLATE_STYLE_NOTE)
    done_item = next(i for i in items if i["done"])
    updated, changed = engine.set_checkbox(TEMPLATE_STYLE_NOTE, done_item["raw_line"], False)

    assert changed is True
    assert "- [ ] **Book the room** — Assigned to: Sam — Due: 2026-08-01" in updated


def test_set_checkbox_reports_no_change_when_line_is_gone():
    """If the note was hand-edited, we must not guess at which line to rewrite."""
    updated, changed = engine.set_checkbox(TEMPLATE_STYLE_NOTE, "- [ ] a line that isn't there", True)
    assert changed is False
    assert updated == TEMPLATE_STYLE_NOTE


def test_write_back_round_trips_through_the_parser():
    """Ticking an item must produce a line the parser still recognises, otherwise
    a later rescan would lose track of it."""
    items = engine.parse_action_items(TEMPLATE_STYLE_NOTE)
    updated, _ = engine.set_checkbox(TEMPLATE_STYLE_NOTE, items[0]["raw_line"], True)

    reparsed = engine.parse_action_items(updated)
    assert len(reparsed) == len(items)
    match = next(i for i in reparsed if i["text"] == "Send the revised deck")
    assert match["done"] is True
    assert match["owner"] == "Priya"  # metadata survived the rewrite
