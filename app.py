import csv
import io
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta, timezone
import streamlit as st
from pathlib import Path
import config
import db
import engine
import importers
import lms
import storage

APP_VERSION = "0.5.0"
# Auto-refresh a connected feed if it hasn't been checked in this long.
FEED_STALE_HOURS = 6
NOTE_FILENAME = "note.md"
AUDIO_FILENAME = "recording.wav"


def _display_title(md_path: Path) -> str:
    """A note's title comes from its folder name (per-note layout), or its
    own filename for legacy notes saved flat as <category>/<slug>.md."""
    stem = md_path.parent.name if md_path.name == NOTE_FILENAME else md_path.stem
    return stem.replace("_", " ").title()


def _audio_path(md_path: Path) -> Path:
    return md_path.parent / AUDIO_FILENAME if md_path.name == NOTE_FILENAME else md_path.with_suffix(".wav")


def _safe_index(options, value, fallback=0):
    return options.index(value) if value in options else fallback


def _effective_categories():
    """Built-in categories, plus any the user has added in Settings."""
    custom = db.get_pref_json("custom_categories", default=[])
    return config.SUBSECTIONS + [c for c in custom if c not in config.SUBSECTIONS]


def _effective_templates():
    """Built-in prompt templates, plus any the user has added in Settings."""
    merged = dict(config.TEMPLATES)
    merged.update(db.get_pref_json("custom_templates", default={}))
    return merged


def _effective_ollama_models():
    """Built-in Ollama model choices, plus any the user has added in Settings."""
    custom = db.get_pref_json("custom_ollama_models", default=[])
    return config.OLLAMA_MODELS + [m for m in custom if m not in config.OLLAMA_MODELS]


def _build_backup_zip() -> bytes:
    """Zip the whole library for backup/export: every note and recording, plus
    the index — which lives outside the notes folder but holds the tags, so a
    backup without it would silently lose them."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in config.STORAGE_DIR.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=Path("notes") / path.relative_to(config.STORAGE_DIR))
        index = db.index_path()
        if index.exists():
            zf.write(index, arcname="echopad-index.db")
    return buf.getvalue()


def _note_path(category: str, filename: str) -> Path:
    return config.STORAGE_DIR / category / filename


def _read_note(category: str, filename: str) -> str:
    try:
        return _note_path(category, filename).read_text(encoding="utf-8")
    except OSError:
        return ""


def _sync_action_items(md_path: Path, note_text: str) -> int:
    """Re-read a note's checkbox tasks into the index. Cheap and deterministic —
    the templates already emit tasks as Markdown checkboxes, so no model call."""
    category, filename = db.relative_key(md_path)
    items = engine.parse_action_items(note_text)
    db.replace_action_items(category, filename, items)
    return len(items)


def _resync_all_action_items() -> int:
    """Re-derive every note's action items from its file.

    Runs once per session so tasks are always what the notes actually say —
    including notes synced down from another computer or edited outside the app,
    which otherwise wouldn't show up until someone hit Rescan by hand. Parsing
    is a regex over text already on disk, so this stays cheap.
    """
    notes_seen = 0
    for note in db.search(""):
        body = _read_note(note["category"], note["filename"])
        if body:
            db.replace_action_items(
                note["category"], note["filename"], engine.parse_action_items(body))
            notes_seen += 1
    return notes_seen


def _complete_action_item(item: dict, done: bool) -> bool:
    """Tick an item off in the note file itself, then in the index.

    The Markdown is the source of truth for what's outstanding, so if the line
    can no longer be found (the note was edited by hand) we leave the file alone
    and say so rather than silently diverging.
    """
    md_path = _note_path(item["category"], item["filename"])
    text = _read_note(item["category"], item["filename"])
    updated, changed = engine.set_checkbox(text, item["raw_line"], done)
    if not changed:
        return False
    try:
        md_path.write_text(updated, encoding="utf-8")
    except OSError:
        return False
    new_line, _ = engine.set_checkbox(item["raw_line"], item["raw_line"], done)
    db.set_action_done(item["id"], done, new_raw_line=new_line)
    return True


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_local(iso_utc: str) -> datetime:
    """Parse a stored UTC timestamp into the machine's local timezone."""
    return datetime.fromisoformat(iso_utc).astimezone()


def _due_label(deadline: dict, now: datetime = None) -> str:
    """Human phrasing for when something is due, relative to now."""
    now = now or datetime.now().astimezone()
    due = _to_local(deadline["due_at"])
    when = due.strftime("%a %d %b") if deadline["all_day"] else due.strftime("%a %d %b, %H:%M")

    days = (due.date() - now.date()).days
    if due < now:
        overdue_days = (now.date() - due.date()).days
        if overdue_days == 0:
            return f"{when} · ⚠️ overdue"
        return f"{when} · ⚠️ {overdue_days} day{'s' if overdue_days != 1 else ''} overdue"
    if days == 0:
        return f"{when} · today"
    if days == 1:
        return f"{when} · tomorrow"
    if days <= 7:
        return f"{when} · in {days} days"
    return when


def _sync_feed(source: dict) -> tuple:
    """Fetch and store one feed. Returns (ok, message)."""
    try:
        items, warnings = lms.fetch_and_parse(source["url"])
    except lms.FeedError as exc:
        db.update_lms_source_status(source["id"], f"error: {exc}")
        return False, str(exc)

    added, updated, skipped = db.upsert_deadlines(source["id"], items)
    removed = db.prune_deadlines_missing_from_feed(
        source["id"], [item["uid"] for item in items])
    db.update_lms_source_status(source["id"], "ok", event_count=len(items))

    parts = [f"{added} new"] if added else []
    if updated:
        parts.append(f"{updated} updated")
    if removed:
        parts.append(f"{removed} removed")
    if skipped:
        parts.append(f"{skipped} kept as you edited them")
    summary = ", ".join(parts) if parts else "no changes"
    return True, "; ".join([f"{source['name']}: {summary}", *warnings])


def _feed_is_stale(source: dict) -> bool:
    if not source.get("last_synced"):
        return True
    try:
        last = datetime.fromisoformat(source["last_synced"])
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - last > timedelta(hours=FEED_STALE_HOURS)


def _clear_edit_dialog_state(deadline_id: int) -> None:
    """Forget this deadline's form state once the dialog has done its job, so a
    later reopen reflects what's actually stored — after a revert, especially."""
    for field in ("title", "course", "date", "allday", "time", "kind", "desc"):
        st.session_state.pop(f"ed_{field}_{deadline_id}", None)


@st.dialog("Edit deadline")
def _edit_deadline_dialog(deadline: dict):
    """Edit any deadline — including one that came from an LMS feed.

    Editing a feed deadline marks it as yours, so syncing won't overwrite it;
    the LMS's own version is kept so the edit can be undone.
    """
    from_feed = deadline["source_id"] is not None
    if from_feed and deadline["user_edited"]:
        st.caption(
            f"Edited by you. Your LMS currently says: **{deadline['feed_title']}** due "
            f"{_to_local(deadline['feed_due_at']).strftime('%a %d %b, %H:%M')}."
        )
    elif from_feed:
        st.caption("This came from a connected feed. Your edits will survive future syncs.")

    # Keys are scoped to this deadline. With a shared key, Streamlit would reuse
    # the value already in session state and ignore `value=`, so opening Edit on a
    # second deadline would show — and then save — the first one's details.
    k = deadline["id"]
    title = st.text_input("Title", value=deadline["title"], key=f"ed_title_{k}")
    course = st.text_input("Course", value=deadline["course"] or "", key=f"ed_course_{k}")

    current = _to_local(deadline["due_at"])
    col_date, col_time = st.columns(2)
    with col_date:
        new_date = st.date_input("Due date", value=current.date(), key=f"ed_date_{k}")
    with col_time:
        all_day = st.checkbox("All day", value=bool(deadline["all_day"]), key=f"ed_allday_{k}")
        new_time = st.time_input("Due time", value=current.time().replace(second=0),
                                 key=f"ed_time_{k}", disabled=all_day)

    kind = st.selectbox("Type", ["assignment", "event"],
                        index=0 if deadline["kind"] == "assignment" else 1, key=f"ed_kind_{k}")
    notes = st.text_area("Notes", value=deadline["description"] or "", height=100,
                         key=f"ed_desc_{k}")

    st.divider()
    col_cancel, col_save = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with col_save:
        if st.button("💾 Save", type="primary", use_container_width=True):
            if not title.strip():
                st.error("Give the deadline a title.")
                return
            chosen = time(23, 59) if all_day else new_time
            local_due = datetime.combine(new_date, chosen).astimezone()
            db.update_deadline(
                deadline["id"], title=title.strip(), course=course.strip(),
                due_at=local_due.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
                all_day=all_day, kind=kind, description=notes.strip(),
            )
            st.session_state["flash"] = f'Updated "{title.strip()}".'
            _clear_edit_dialog_state(k)
            st.rerun()

    if from_feed and deadline["user_edited"] and deadline["feed_title"]:
        if st.button("↩️ Reset to the LMS version", use_container_width=True):
            db.revert_deadline_to_feed(deadline["id"])
            st.session_state["flash"] = "Reset to what your LMS says."
            _clear_edit_dialog_state(k)
            st.rerun()

    if st.button("🗑️ Delete this deadline", use_container_width=True):
        db.delete_deadline(deadline["id"])
        st.session_state["flash"] = f'Deleted "{deadline["title"]}".'
        _clear_edit_dialog_state(k)
        st.rerun()


def _delete_note(md_path: Path) -> None:
    """Permanently remove a note's markdown, audio, and index entry."""
    category, filename = db.relative_key(md_path)
    if md_path.name == NOTE_FILENAME:
        # Per-note folder layout: remove the whole folder (note + audio + anything else in it).
        shutil.rmtree(md_path.parent, ignore_errors=True)
    else:
        # Legacy flat layout: this note's own files live in the category folder.
        md_path.unlink(missing_ok=True)
        _audio_path(md_path).unlink(missing_ok=True)
        storage.meta_path(md_path, NOTE_FILENAME).unlink(missing_ok=True)
    # cascade: an intentional delete should take the note's cards and tasks with it
    db.delete_note(category, filename, cascade=True)


@st.dialog("Delete this note?")
def _confirm_delete_dialog(md_path: Path):
    display_name = _display_title(md_path)
    st.warning(f"This will permanently delete **{display_name}** and its audio recording. This can't be undone.")
    col_cancel, col_confirm = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with col_confirm:
        if st.button("🗑️ Delete Permanently", type="primary", use_container_width=True):
            _delete_note(md_path)
            st.session_state["selected_file"] = None
            st.session_state["flash"] = f'Deleted "{display_name}".'
            st.rerun()


@st.dialog("Change where notes are stored")
def _confirm_storage_dialog(target: Path, note_count: int):
    st.caption("New location:")
    st.code(str(target), language=None)

    move_label = f"Move my {note_count} existing note{'s' if note_count != 1 else ''} there"
    choice = move_label if note_count else "Switch without moving anything"
    if note_count:
        choice = st.radio(
            "What should happen to the notes already saved?",
            [move_label, "Leave them where they are (start fresh in the new folder)"],
            index=0,
        )
    st.caption(
        "Notes are copied and verified before anything is removed — if a copy fails, "
        "the move is rolled back and your current folder is left untouched."
    )

    col_cancel, col_confirm = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with col_confirm:
        if st.button("✅ Use This Location", type="primary", use_container_width=True):
            messages = []
            if note_count and choice == move_label:
                result = storage.move_library(config.STORAGE_DIR, target)
                if result["failed"]:
                    first = result["failed"][0]
                    st.error(
                        f"Couldn't move `{first['file']}` ({first['error']}). "
                        "Nothing was changed — your notes are still in the current folder."
                    )
                    return
                messages.append(f"moved {result['moved']} file(s)")
                if result["conflicts"]:
                    messages.append(
                        f"skipped {len(result['conflicts'])} already present at the destination"
                    )
            config.set_storage_dir(target)
            db.migrate_legacy_index()
            st.session_state.pop("index_synced", None)  # re-index against the new location
            st.session_state["selected_file"] = None
            detail = f" ({', '.join(messages)})" if messages else ""
            st.session_state["flash"] = f"Notes now stored in {target}{detail}."
            st.rerun()


st.set_page_config(page_title="EchoPad", page_icon="🎙️", layout="wide")

if not engine.check_ollama_status():
    st.error("⚠️ **Ollama is not running!** Please start Ollama (`ollama serve`) and refresh.")
    st.stop()

# Sync the index with whatever's actually on disk: adopt an index from an older
# version, drop entries for notes renamed/moved/deleted outside the app, then
# index anything new — including notes synced down from another machine via
# OneDrive/Google Drive. Cheap, so we only do it once per session.
if "index_synced" not in st.session_state:
    db.migrate_legacy_index()
    db.prune_missing()
    db.rebuild_from_disk()
    _resync_all_action_items()
    st.session_state["index_synced"] = True

if db.get_pref("compact_mode", default="false") == "true":
    st.markdown(
        "<style>.block-container {padding-top: 2rem; padding-bottom: 2rem;} "
        "div[data-testid='stVerticalBlockBorderWrapper'] {padding: 0.25rem;}</style>",
        unsafe_allow_html=True,
    )

st.title("🎙️ EchoPad — AI Voice Notebook")
st.caption("Study smarter. Interview sharper. Network better. 100% local and private.")

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅")

all_categories = _effective_categories()
all_templates = _effective_templates()
all_ollama_models = _effective_ollama_models()

# --- SIDEBAR CONFIG ---
st.sidebar.header("⚙️ Settings & Pipeline")
default_whisper = db.get_pref("default_whisper_model", default=config.DEFAULT_WHISPER_MODEL)
default_ollama = db.get_pref("default_ollama_model", default=config.DEFAULT_OLLAMA_MODEL)
selected_whisper = st.sidebar.selectbox(
    "Whisper Model", config.WHISPER_MODELS, index=_safe_index(config.WHISPER_MODELS, default_whisper, fallback=1)
)
selected_ollama = st.sidebar.selectbox(
    "Ollama Model", all_ollama_models, index=_safe_index(all_ollama_models, default_ollama, fallback=0)
)
translate_option = st.sidebar.checkbox("🌐 Translate to English", value=False)

st.sidebar.divider()

# --- FULL-TEXT SEARCH ---
st.sidebar.header("🔍 Full-Text Search")
search_query = st.sidebar.text_input("Search notes...", placeholder="e.g. latency, vector, Q3")

search_results = engine.search_notes(search_query) if search_query else []

if search_query:
    if search_results:
        st.sidebar.caption(f"Found {len(search_results)} result(s)")
        for res in search_results:
            if st.sidebar.button(f"📄 {res['name']}", key=str(res['path']), use_container_width=True):
                st.session_state["selected_file"] = res['path']
            st.sidebar.caption(res["snippet"])
    else:
        st.sidebar.caption("No matches found.")

# --- BROWSE BY TAG ---
all_tags = db.all_tags()
if all_tags:
    tag_filter = st.sidebar.selectbox("🏷️ Browse by Tag", ["None"] + all_tags)
    if tag_filter != "None":
        tag_results = db.search("", tag=tag_filter)
        st.sidebar.caption(f"{len(tag_results)} note(s) tagged \"{tag_filter}\"")
        for res in tag_results:
            note_path = config.STORAGE_DIR / res["category"] / res["filename"]
            if st.sidebar.button(f"🏷️ {res['title']} ({res['category']})", key=f"tag_{note_path}", use_container_width=True):
                st.session_state["selected_file"] = note_path

st.sidebar.divider()
st.sidebar.header("📁 Subsections")
selected_category = st.sidebar.selectbox("Select Category", all_categories)
cat_dir = config.STORAGE_DIR / selected_category
cat_dir.mkdir(exist_ok=True)

# Each note lives in its own folder (category/slug/note.md); legacy notes
# saved before that layout existed may still sit flat as category/slug.md.
note_folders = sorted(d.name for d in cat_dir.iterdir() if d.is_dir() and (d / NOTE_FILENAME).exists())
legacy_notes = sorted(f.name for f in cat_dir.glob("*.md"))
existing_notes = note_folders + legacy_notes
selected_note_name = st.sidebar.selectbox("📖 Saved Notes", ["None"] + existing_notes)

# Override selection if search result clicked
active_file = st.session_state.get("selected_file", None)
if selected_note_name != "None" and not active_file:
    active_file = (
        cat_dir / selected_note_name / NOTE_FILENAME
        if selected_note_name in note_folders
        else cat_dir / selected_note_name
    )

st.sidebar.divider()
st.sidebar.caption(f"EchoPad v{APP_VERSION} · 100% local & private")

# --- MAIN WORKSPACE ---
if active_file and active_file.exists():
    note_title = _display_title(active_file)
    st.subheader(f"📖 Reading: {note_title}")

    # Audio Playback
    audio_file_path = _audio_path(active_file)
    if audio_file_path.exists():
        st.audio(str(audio_file_path))

    with open(active_file, "r", encoding="utf-8") as f:
        note_content = f.read()

    note_category, note_filename = db.relative_key(active_file)
    current_row = db.get_note(note_category, note_filename)
    st.caption(
        f"{note_category} · {len(note_content.split()):,} words"
        + (f" · saved {current_row['created_at']}" if current_row else "")
    )

    # Tags
    current_tags = current_row["tags"] if current_row else ""
    new_tags = st.text_input("🏷️ Tags (comma-separated)", value=current_tags, key=f"tags_{active_file}")
    if new_tags != current_tags:
        db.update_tags(note_category, note_filename, new_tags)
        storage.write_note_meta(active_file, NOTE_FILENAME, tags=new_tags)
        st.session_state["flash"] = "Tags updated."
        st.rerun()

    # Rename — keeps the folder name, index entry, and title in step
    with st.expander("🏷️ Rename Note", expanded=False):
        st.caption("Renaming also renames the note's folder on disk, so it stays easy to find.")
        rename_to = st.text_input("New title", value=note_title, key=f"rename_{active_file}")
        if st.button("Rename", key=f"rename_btn_{active_file}"):
            cleaned = rename_to.strip()
            if not cleaned:
                st.toast("Enter a title first.", icon="⚠️")
            elif cleaned == note_title:
                st.toast("That's already the title.", icon="ℹ️")
            else:
                try:
                    new_md, new_key = storage.rename_note(active_file, cleaned, NOTE_FILENAME)
                except (OSError, FileExistsError) as exc:
                    st.error(f"Couldn't rename: {exc}")
                else:
                    db.rename_note(note_category, note_filename, new_key, cleaned)
                    storage.write_note_meta(new_md, NOTE_FILENAME, title=cleaned)
                    st.session_state["selected_file"] = new_md
                    st.session_state["flash"] = f'Renamed to "{cleaned}".'
                    st.rerun()

    # Interactive In-App Editor
    with st.expander("✏️ Edit Note Content", expanded=False):
        edited_content = st.text_area("Edit Markdown", value=note_content, height=300)
        if st.button("💾 Save Changes"):
            with open(active_file, "w", encoding="utf-8") as f:
                f.write(edited_content)
            db.update_word_count(note_category, note_filename, len(edited_content.split()))
            storage.write_note_meta(active_file, NOTE_FILENAME, word_count=len(edited_content.split()))
            # Editing may have added, reworded, or ticked off tasks
            _sync_action_items(active_file, edited_content)
            st.session_state["flash"] = "Note updated successfully."
            st.rerun()

    # This note's action items, tickable in place. Narrowed by category in SQL so
    # opening one note doesn't pull every task in the library into memory.
    note_tasks = [t for t in db.action_items(category=note_category, include_done=True)
                  if t["filename"] == note_filename]
    if note_tasks:
        open_count = sum(1 for t in note_tasks if not t["done"])
        with st.expander(f"✅ Action Items ({open_count} open of {len(note_tasks)})", expanded=bool(open_count)):
            for task in note_tasks:
                ticked = st.checkbox(task["text"], value=bool(task["done"]), key=f"note_task_{task['id']}")
                bits = [b for b in (f"👤 {task['owner']}" if task["owner"] else "",
                                    f"📅 {task['due']}" if task["due"] else "") if b]
                if bits:
                    st.caption(" · ".join(bits))
                if ticked != bool(task["done"]):
                    ok = _complete_action_item(task, ticked)
                    st.session_state["flash"] = (
                        ("Marked done." if ticked else "Reopened.") if ok
                        else "That line has changed in the note — rescan from the Work tab."
                    )
                    st.rerun()

    # Attach supplementary material — a handout, a photo of the board, a slide deck
    with st.expander("📎 Attachments", expanded=False):
        existing = sorted(
            p for p in active_file.parent.iterdir()
            if p.is_file() and p.name not in (NOTE_FILENAME, AUDIO_FILENAME, storage.META_FILENAME)
        ) if active_file.name == NOTE_FILENAME else []
        if existing:
            for attachment in existing:
                acol, dcol = st.columns([4, 1])
                acol.write(f"📄 {attachment.name}  ·  {attachment.stat().st_size / 1024:,.0f} KB")
                with dcol:
                    st.download_button("Download", data=attachment.read_bytes(),
                                       file_name=attachment.name, key=f"dl_{attachment.name}",
                                       use_container_width=True)
        else:
            st.caption("Nothing attached yet.")

        if active_file.name == NOTE_FILENAME:
            extra = st.file_uploader(
                "Attach a file to this note", key=f"attach_{active_file}",
                help="Anything relevant — a handout, slides, a photo of the whiteboard. "
                     "Stored inside the note's own folder.",
            )
            if extra is not None and st.button("📎 Attach", key=f"attach_btn_{active_file}"):
                target = active_file.parent / Path(extra.name).name
                if target.exists():
                    st.warning(f"`{target.name}` is already attached to this note.")
                else:
                    target.write_bytes(extra.getvalue())
                    st.session_state["flash"] = f"Attached {target.name}."
                    st.rerun()
        else:
            st.caption("Attachments need the per-note folder layout; this is a legacy flat note.")

    # Study & follow-up actions derived from this note
    with st.expander("✨ Make Something From This Note", expanded=False):
        make_cards, make_followup = st.columns(2)
        with make_cards:
            if st.button("📇 Make Flashcards", key=f"mk_cards_{active_file}", use_container_width=True):
                with st.spinner(f"Writing cards with {selected_ollama}…"):
                    try:
                        cards = engine.generate_flashcards(note_content, count=10, model_name=selected_ollama)
                    except Exception as exc:
                        cards = None
                        st.error(f"Card generation failed: {exc}")
                if cards is not None:
                    if cards:
                        added = db.add_flashcards(note_category, note_filename, cards)
                        st.session_state["flash"] = f"Added {added} card(s) — review them in the Study tab."
                        st.rerun()
                    else:
                        st.warning("The model didn't return usable Q/A pairs. Try again or use a larger model.")
        with make_followup:
            if st.button("✉️ Draft Follow-Up", key=f"mk_fu_{active_file}", use_container_width=True):
                with st.spinner(f"Drafting with {selected_ollama}…"):
                    try:
                        st.session_state["followup_draft"] = engine.generate_followup(
                            note_content, model_name=selected_ollama)
                        st.session_state["followup_for"] = note_title
                        st.session_state["flash"] = "Draft ready — see the Work tab."
                    except Exception as exc:
                        st.error(f"Drafting failed: {exc}")
        card_count = len([c for c in db.all_flashcards(category=note_category)
                          if c["filename"] == note_filename])
        if card_count:
            st.caption(f"📇 {card_count} flashcard(s) already made from this note.")

    st.markdown(edited_content if 'edited_content' in locals() else note_content)

    # Multi-Format Export Buttons
    export_stem = note_title.lower().replace(" ", "_")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📥 Download .MD", data=note_content, file_name=f"{export_stem}.md", mime="text/markdown")
    with col2:
        html_data = engine.convert_md_to_html(note_content)
        st.download_button("🌐 Download .HTML", data=html_data, file_name=f"{export_stem}.html", mime="text/html")
    with col3:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = os.path.join(tmp_dir, f"{export_stem}.pdf")
            engine.convert_md_to_pdf(note_content, pdf_path)
            with open(pdf_path, "rb") as pf:
                pdf_bytes = pf.read()
        st.download_button("📄 Download .PDF", data=pdf_bytes, file_name=f"{export_stem}.pdf", mime="application/pdf")

    st.divider()
    col_close, col_delete = st.columns(2)
    with col_close:
        if st.button("❌ Close Note", use_container_width=True):
            st.session_state["selected_file"] = None
            st.rerun()
    with col_delete:
        if st.button("🗑️ Delete Note", use_container_width=True):
            _confirm_delete_dialog(active_file)

else:
    tab_dashboard, tab_new_note, tab_deadlines, tab_study, tab_work, tab_settings = st.tabs(
        ["🏠 Dashboard", "🎙️ New Note", "📅 Deadlines", "📚 Study", "✅ Work", "⚙️ Settings"]
    )

    # ============================== DASHBOARD ==============================
    with tab_dashboard:
        counts = db.counts_by_category()
        total_notes = sum(counts.values())
        if total_notes:
            card_stats = db.flashcard_stats()
            task_stats = db.action_item_stats()
            due_stats = db.deadline_stats(horizon_days=7)
            stat_cols = st.columns(5)
            stat_cols[0].metric("Total Notes", total_notes)
            stat_cols[1].metric("Words Captured", f"{db.total_word_count():,}")
            stat_cols[2].metric(
                "Due This Week", due_stats["due_soon"],
                delta=f"{due_stats['overdue']} overdue" if due_stats["overdue"] else None,
                delta_color="inverse",
                help="Assignment deadlines from your LMS calendar, in the Deadlines tab",
            )
            stat_cols[3].metric("Cards Due", card_stats["due"],
                                help="Flashcards ready to review in the Study tab")
            stat_cols[4].metric("Open Tasks", task_stats["open"],
                                help="Unticked action items across all your notes")

            # Busiest categories, capped so the row stays readable even with many custom ones
            active_categories = sorted((c for c in all_categories if counts.get(c, 0) > 0), key=lambda c: -counts[c])
            shown_categories = active_categories[:6]
            if shown_categories:
                cat_cols = st.columns(len(shown_categories))
                for col, cat in zip(cat_cols, shown_categories):
                    col.metric(cat, counts[cat])
            if len(active_categories) > len(shown_categories):
                st.caption(f"+ {len(active_categories) - len(shown_categories)} more categor{'y' if len(active_categories) - len(shown_categories) == 1 else 'ies'} with notes")

            with st.expander(f"🕒 Recently Added ({min(total_notes, 10)})", expanded=True):
                for note in db.recent_notes(limit=10):
                    note_path = config.STORAGE_DIR / note["category"] / note["filename"]
                    with st.container(border=True):
                        info_col, action_col = st.columns([5, 1])
                        with info_col:
                            st.markdown(f"**📄 {note['title']}**")
                            st.caption(f"{note['category']} · {note['created_at']}" + (f" · 🏷️ {note['tags']}" if note["tags"] else ""))
                        with action_col:
                            if st.button("Open →", key=f"recent_{note_path}", use_container_width=True):
                                st.session_state["selected_file"] = note_path
                                st.rerun()
        else:
            st.subheader("👋 Welcome to EchoPad")
            st.info("You haven't recorded any notes yet. Head to the **New Note** tab to record or upload your first one — it'll show up here once saved.")

    # ============================== NEW NOTE ==============================
    with tab_new_note:
        title = st.text_input(
            "Note Title",
            placeholder="e.g. Organic Chemistry Midterm Review, or Interview Debrief — Acme Corp",
        )
        # Group the picker so a 12-template list stays navigable
        template_names = list(all_templates.keys())
        study_first = [n for n in config.STUDY_TEMPLATES if n in template_names]
        work_next = [n for n in config.WORK_TEMPLATES if n in template_names]
        other = [n for n in template_names if n not in study_first + work_next]
        ordered_templates = study_first + work_next + other
        selected_template = st.selectbox(
            "Select Prompt Template", ordered_templates,
            help="Study templates come first, then work templates, then anything you've added yourself.",
        )
        note_tags = st.text_input("🏷️ Tags (comma-separated, optional)", placeholder="e.g. midterm, chapter-4, orgo")

        tab_record, tab_upload, tab_import = st.tabs(
            ["🎙️ Live Mic Record", "📁 Upload Audio File", "📄 Import a Document"]
        )
        audio_source = None
        imported_text = None
        imported_file = None

        with tab_record:
            rec_data = st.audio_input("Record live from browser mic")
            if rec_data:
                audio_source = rec_data

        with tab_upload:
            up_data = st.file_uploader("Upload audio file", type=["mp3", "m4a", "wav"])
            if up_data:
                audio_source = up_data

        with tab_import:
            st.caption(
                "Already have notes as a PDF, Word document, text file, or a photo of a "
                "whiteboard or handout? Import it and EchoPad will structure it with the "
                "same templates it uses for recordings. The original file is filed with the note."
            )
            doc_data = st.file_uploader(
                "Import a document or image", type=importers.UPLOAD_TYPES, key="import_doc",
            )
            if doc_data:
                try:
                    extracted, import_warnings = importers.extract_text(doc_data.name, doc_data.getvalue())
                except importers.ImportFailed as exc:
                    st.error(str(exc))
                else:
                    for warning in import_warnings:
                        st.warning(warning)
                    if extracted.strip():
                        imported_text, imported_file = extracted, doc_data
                        st.success(f"Read {len(extracted.split()):,} words from `{doc_data.name}`.")
                        with st.expander("Preview extracted text", expanded=False):
                            st.text(extracted[:3000] + ("\n…" if len(extracted) > 3000 else ""))
                    else:
                        st.error(
                            "No text could be read from that file. If it's a scanned PDF, "
                            "export the pages as images and import those instead."
                        )

        has_source = bool(audio_source or imported_text)
        if not title:
            st.info("👆 Give your note a title to get started.")
        elif not has_source:
            st.info("🎙️ Record, upload audio, or import a document above to continue.")

        if has_source and title:
            if audio_source:
                st.caption("First-time use of a Whisper model size downloads it locally — this only happens once.")
            if st.button("✨ Process & Generate Note", type="primary"):
                source_note = None
                with st.status("Processing...", expanded=True) as status:
                    audio_bytes = None
                    if audio_source:
                        st.write("👂 Transcribing audio locally...")
                        audio_bytes = audio_source.getvalue()
                        progress_line = st.empty()

                        def _report_progress(text_so_far, segment):
                            progress_line.caption(f"📝 ~{len(text_so_far.split())} words so far (up to {segment.end:.0f}s)...")

                        transcript = engine.transcribe_audio(
                            audio_bytes,
                            model_size=selected_whisper,
                            translate=translate_option,
                            on_progress=_report_progress,
                        )
                        progress_line.empty()
                    else:
                        st.write(f"📄 Using text from `{imported_file.name}`...")
                        transcript = imported_text
                        source_note = importers.describe_source(imported_file.name)

                    st.write(f"🧠 Summarizing with {selected_ollama} ({selected_template} Template)...")
                    template_text = all_templates.get(selected_template, config.TEMPLATES["Meeting"])
                    summary = engine.generate_summary(transcript, template=template_text, model_name=selected_ollama)
                    status.update(label="Complete!", state="complete", expanded=False)

                source_line = f"\n*Source: {source_note}*" if source_note else ""
                body_heading = "📄 Imported Text" if source_note else "📝 Raw Transcript"
                full_document = (
                    f"# {title}\n*Category: {selected_category}*{source_line}\n\n{summary}"
                    f"\n\n---\n### {body_heading}\n{transcript}"
                )

                # Each note gets its own folder — e.g. notes/Lectures/organic_chemistry_midterm_review/ —
                # so recordings, notes, and exports for that note stay together and are easy to
                # browse in Windows/Mac file explorers, right alongside the app.
                safe_slug = storage.unique_slug(cat_dir, storage.slugify(title))
                note_dir = cat_dir / safe_slug
                note_dir.mkdir(parents=True, exist_ok=True)

                # Save Markdown File
                md_path = note_dir / NOTE_FILENAME
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(full_document)

                # Save the source material next to the note: the recording for
                # playback, or the original document so the note is traceable to it.
                if audio_bytes is not None:
                    (note_dir / AUDIO_FILENAME).write_bytes(audio_bytes)
                elif imported_file is not None:
                    safe_name = Path(imported_file.name).name
                    (note_dir / f"source_{safe_name}").write_bytes(imported_file.getvalue())

                # Index in DB for fast search, tags, and the dashboard...
                db.add_note(
                    title=title,
                    category=selected_category,
                    filename=f"{safe_slug}/{NOTE_FILENAME}",
                    template=selected_template,
                    tags=note_tags.strip(),
                    word_count=len(full_document.split()),
                )
                # ...and alongside the note itself, so the folder stays
                # self-describing if it's moved, synced, or re-indexed.
                saved_row = db.get_note(selected_category, f"{safe_slug}/{NOTE_FILENAME}")
                storage.write_note_meta(
                    md_path, NOTE_FILENAME,
                    title=title,
                    tags=note_tags.strip(),
                    template=selected_template,
                    word_count=len(full_document.split()),
                    created_at=saved_row["created_at"] if saved_row else None,
                )

                # Any checkbox tasks the template produced become tracked items
                # in the Work tab straight away — no extra step, no model call.
                task_count = _sync_action_items(md_path, full_document)

                saved_what = "note and recording" if audio_bytes is not None else "note and source file"
                st.success(f"Saved {saved_what} to `{selected_category}/{safe_slug}/`!")
                if task_count:
                    st.info(f"✅ Found {task_count} action item(s) — see the **Work** tab.")
                st.markdown(full_document)

    # ============================= DEADLINES ==============================
    with tab_deadlines:
        sources = db.lms_sources()

        # Refresh quietly if a feed hasn't been checked in a while, so deadlines
        # are current without the student having to remember to sync.
        if sources and db.get_pref("auto_sync_feeds", default="true") == "true" \
                and "feeds_auto_synced" not in st.session_state:
            st.session_state["feeds_auto_synced"] = True
            stale = [s for s in sources if _feed_is_stale(s)]
            if stale:
                with st.spinner(f"Refreshing {len(stale)} calendar feed(s)…"):
                    problems = [msg for ok, msg in (_sync_feed(s) for s in stale) if not ok]
                if problems:
                    st.warning("Couldn't refresh a feed: " + problems[0])
                sources = db.lms_sources()

        now_local = datetime.now().astimezone()
        stats = db.deadline_stats(horizon_days=7)
        d1, d2, d3 = st.columns(3)
        d1.metric("Overdue", stats["overdue"])
        d2.metric("Due This Week", stats["due_soon"])
        d3.metric("Open Total", stats["open"])

        show_done_deadlines = st.checkbox("Show completed", value=False, key="show_done_dl")
        upcoming = db.deadlines(include_completed=show_done_deadlines)

        if not upcoming:
            if sources:
                st.info("Nothing outstanding. 🎉")
            else:
                st.info(
                    "No deadlines yet. Connect your LMS calendar below to pull in "
                    "assignment due dates automatically, or add one by hand."
                )
        else:
            overdue = [d for d in upcoming if not d["completed"]
                       and _to_local(d["due_at"]) < now_local]
            # Split by id: a term's worth of deadlines runs to four figures, and
            # `d not in overdue` would compare whole dicts n² times per render.
            overdue_ids = {d["id"] for d in overdue}
            future = [d for d in upcoming if d["id"] not in overdue_ids]

            def render_deadline(item):
                with st.container(border=True):
                    tick_col, body_col, edit_col = st.columns([0.6, 6, 1.2])
                    with tick_col:
                        done = st.checkbox(
                            "Done", value=bool(item["completed"]), key=f"dl_done_{item['id']}",
                            label_visibility="collapsed",
                        )
                    with body_col:
                        badges = []
                        if item["course"]:
                            badges.append(f"`{item['course']}`")
                        if item["kind"] == "event":
                            badges.append("📌 event")
                        if item["user_edited"]:
                            badges.append("✏️ edited by you")
                        if item["source_id"] is None:
                            badges.append("✍️ added by you")
                        heading = f"**{item['title']}**"
                        if item["completed"]:
                            heading = f"~~{item['title']}~~"
                        st.markdown(heading + ("  ·  " + " ".join(badges) if badges else ""))
                        st.caption(_due_label(item, now_local))
                        if item["url"]:
                            st.caption(f"[Open in your LMS ↗]({item['url']})")
                    with edit_col:
                        if st.button("Edit", key=f"dl_edit_{item['id']}", use_container_width=True):
                            _edit_deadline_dialog(item)
                    if done != bool(item["completed"]):
                        db.set_deadline_completed(item["id"], done)
                        st.session_state["flash"] = "Marked done." if done else "Reopened."
                        st.rerun()

            if overdue:
                st.markdown(f"##### ⚠️ Overdue ({len(overdue)})")
                for item in overdue:
                    render_deadline(item)

            if future:
                st.markdown("##### 📆 Coming Up")
                last_header = None
                for item in future:
                    due = _to_local(item["due_at"])
                    days = (due.date() - now_local.date()).days
                    if days < 0:
                        header = "Earlier"
                    elif days == 0:
                        header = "Today"
                    elif days == 1:
                        header = "Tomorrow"
                    elif days <= 7:
                        header = "This week"
                    elif days <= 31:
                        header = "This month"
                    else:
                        header = "Later"
                    if header != last_header:
                        st.caption(f"**{header}**")
                        last_header = header
                    render_deadline(item)

        st.divider()
        with st.expander("➕ Add a deadline by hand", expanded=not upcoming and not sources):
            st.caption(
                "For anything not in a feed — a Gradescope-only problem set, or a date "
                "your professor only announced in class."
            )
            man_title = st.text_input("What's due", key="man_title",
                                      placeholder="e.g. Problem Set 5")
            man_course = st.text_input("Course (optional)", key="man_course",
                                       placeholder="e.g. MATH 240")
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                man_date = st.date_input("Due date", value=date.today() + timedelta(days=7),
                                         key="man_date")
            with mc2:
                man_all_day = st.checkbox("All day", value=False, key="man_allday")
                man_time = st.time_input("Due time", value=time(23, 59), key="man_time",
                                         disabled=man_all_day)
            with mc3:
                man_kind = st.selectbox("Type", ["assignment", "event"], key="man_kind")
            if st.button("➕ Add Deadline", key="man_add", type="primary"):
                if not man_title.strip():
                    st.toast("Give it a title first.", icon="⚠️")
                else:
                    chosen = time(23, 59) if man_all_day else man_time
                    local_due = datetime.combine(man_date, chosen).astimezone()
                    db.add_manual_deadline(
                        title=man_title.strip(), course=man_course.strip(),
                        due_at=local_due.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
                        all_day=man_all_day, kind=man_kind,
                    )
                    st.session_state["flash"] = f'Added "{man_title.strip()}".'
                    st.rerun()

        with st.expander("🔗 Connect your LMS calendar", expanded=not sources):
            st.caption(
                "Canvas, Blackboard, Moodle and others publish a personal calendar feed "
                "containing your assignment due dates. Subscribing to it is read-only: "
                "EchoPad can see your deadlines and can never change anything in your LMS. "
                "No password and no OAuth app required."
            )

            provider = st.selectbox("Which system?", list(lms.PROVIDERS), key="feed_provider")
            st.info(lms.PROVIDERS[provider]["help"])
            st.caption(f"It should look like: `{lms.PROVIDERS[provider]['example']}`")

            feed_url = st.text_input("Calendar feed URL", key="feed_url",
                                     placeholder="https://…  or  webcal://…")
            feed_name = st.text_input("Label (optional)", key="feed_name",
                                      placeholder=f"e.g. {provider} — Fall term")
            if st.button("🔗 Connect & Sync", key="feed_connect", type="primary"):
                try:
                    normalized = lms.normalize_feed_url(feed_url)
                except lms.FeedError as exc:
                    st.error(str(exc))
                else:
                    with st.spinner("Fetching your calendar…"):
                        source_id = db.add_lms_source(
                            feed_name.strip() or provider, provider, normalized)
                        ok, message = _sync_feed(db.get_lms_source(source_id))
                    if ok:
                        st.session_state["flash"] = message
                        st.rerun()
                    else:
                        # Don't leave a broken feed connected on a first attempt
                        db.delete_lms_source(source_id)
                        st.error(message)

            st.markdown(lms.GRADESCOPE_NOTE)

            st.caption(
                "⚠️ Treat a feed URL like a password: anyone with it can read your "
                "calendar. It's stored locally on this computer only. If you ever paste "
                "it somewhere by mistake, reset it in your LMS and reconnect."
            )

        if sources:
            with st.expander(f"🔄 Connected feeds ({len(sources)})", expanded=False):
                auto = db.get_pref("auto_sync_feeds", default="true") == "true"
                new_auto = st.checkbox(
                    f"Refresh automatically when older than {FEED_STALE_HOURS} hours",
                    value=auto, key="auto_sync_feeds_cb",
                )
                if new_auto != auto:
                    db.set_pref("auto_sync_feeds", "true" if new_auto else "false")
                    st.rerun()

                for source in sources:
                    with st.container(border=True):
                        info_col, sync_col, del_col = st.columns([4, 1, 1])
                        with info_col:
                            st.markdown(f"**{source['name']}** · {source['provider']}")
                            last = source["last_synced"]
                            when = _to_local(last).strftime("%d %b %H:%M") if last else "never"
                            status = source["last_status"] or "not synced yet"
                            icon = "✅" if status == "ok" else "⚠️"
                            st.caption(
                                f"{icon} last checked {when} · {source['event_count']} entr"
                                f"{'y' if source['event_count'] == 1 else 'ies'}"
                            )
                            if status != "ok" and status != "not synced yet":
                                st.caption(status)
                        with sync_col:
                            if st.button("Sync", key=f"sync_{source['id']}",
                                         use_container_width=True):
                                with st.spinner("Syncing…"):
                                    ok, message = _sync_feed(source)
                                st.session_state["flash"] = message
                                st.rerun()
                        with del_col:
                            if st.button("Remove", key=f"rmfeed_{source['id']}",
                                         use_container_width=True):
                                db.delete_lms_source(source["id"])
                                st.session_state["flash"] = f"Disconnected {source['name']}."
                                st.rerun()
                st.caption(
                    "Removing a feed deletes the deadlines that came from it. Deadlines you "
                    "added or edited yourself are kept."
                )

    # =============================== STUDY ================================
    with tab_study:
        all_notes = db.search("")
        card_stats = db.flashcard_stats()

        st.markdown("#### 📇 Flashcards")
        s1, s2, s3 = st.columns(3)
        s1.metric("Cards", card_stats["total"])
        s2.metric("Due Now", card_stats["due"])
        s3.metric("Reviewed At Least Once", card_stats["reviewed"])

        if not all_notes:
            st.info("Save a note first — flashcards are generated from your own notes.")
        else:
            with st.expander("➕ Generate cards from a note", expanded=not card_stats["total"]):
                note_labels = {f"{n['title']} — {n['category']}": n for n in all_notes}
                chosen_label = st.selectbox("Note", list(note_labels), key="fc_note")
                how_many = st.slider("How many cards", 5, 25, 10, key="fc_count")
                if st.button("✨ Generate Flashcards", key="fc_generate"):
                    note = note_labels[chosen_label]
                    body = _read_note(note["category"], note["filename"])
                    if not body.strip():
                        st.error("That note's file couldn't be read.")
                    else:
                        with st.spinner(f"Writing {how_many} cards with {selected_ollama}…"):
                            try:
                                cards = engine.generate_flashcards(
                                    body, count=how_many, model_name=selected_ollama)
                            except Exception as exc:
                                cards = None
                                st.error(f"Card generation failed: {exc}")
                        if cards is not None:
                            if not cards:
                                st.warning(
                                    "The model didn't return anything in the expected Q/A format. "
                                    "Trying again, or switching to a larger Ollama model, usually fixes it."
                                )
                            else:
                                added = db.add_flashcards(note["category"], note["filename"], cards)
                                skipped = len(cards) - added
                                msg = f"Added {added} card(s) from “{note['title']}”."
                                if skipped:
                                    msg += f" {skipped} were already saved."
                                st.session_state["flash"] = msg
                                st.rerun()

            # ---- Review session ----
            due = db.due_flashcards(limit=1)
            if card_stats["total"] and not due:
                st.success("🎉 Nothing due right now — everything's scheduled for later.")
            elif due:
                card = due[0]
                st.markdown(f"##### Review — {card_stats['due']} card(s) due")
                with st.container(border=True):
                    st.markdown(f"**{card['question']}**")
                    revealed = st.session_state.get("revealed_card") == card["id"]
                    if not revealed:
                        if st.button("Show answer", key="fc_reveal", use_container_width=True):
                            st.session_state["revealed_card"] = card["id"]
                            st.rerun()
                    else:
                        st.info(card["answer"])
                        st.caption(
                            f"Seen {card['reps']}× · ease {card['ease']:.2f}"
                            + (f" · lapsed {card['lapses']}×" if card["lapses"] else "")
                        )
                        g1, g2, g3 = st.columns(3)
                        grades = (("😖 Again", "again", g1), ("🙂 Good", "good", g2), ("😎 Easy", "easy", g3))
                        for label, grade, column in grades:
                            with column:
                                if st.button(label, key=f"fc_{grade}", use_container_width=True):
                                    result = db.review_flashcard(card["id"], grade)
                                    st.session_state.pop("revealed_card", None)
                                    when = "again today" if result["interval_days"] == 0 else f"in {result['interval_days']} day(s)"
                                    st.session_state["flash"] = f"Scheduled {when}."
                                    st.rerun()

            if card_stats["total"]:
                rows = db.all_flashcards()
                buffer = io.StringIO()
                writer = csv.writer(buffer)
                writer.writerow(["Question", "Answer", "Category", "Source Note", "Due"])
                for row in rows:
                    writer.writerow([row["question"], row["answer"], row["category"],
                                     row["filename"], row["due_at"]])
                st.download_button(
                    "⬇️ Export all cards (.csv for Anki / Quizlet)",
                    data=buffer.getvalue(), file_name="echopad_flashcards.csv", mime="text/csv",
                    key="fc_export",
                )

        st.divider()
        st.markdown("#### 📖 Build a Study Guide")
        st.caption(
            "Merge several notes into one revision document — grouped by theme rather than "
            "by lecture, with a glossary, likely exam questions, and the topics your notes "
            "cover only thinly. Saved as a new note."
        )
        if len(all_notes) < 2:
            st.info("You'll need at least two saved notes to merge.")
        else:
            guide_labels = {f"{n['title']} — {n['category']}": n for n in all_notes}
            picked_labels = st.multiselect(
                "Notes to merge", list(guide_labels),
                help="Pick the lectures and readings for one exam or topic.",
                key="guide_notes",
            )
            guide_title = st.text_input(
                "Title for the study guide", key="guide_title",
                placeholder="e.g. BIO 201 Midterm 2 — Study Guide",
            )
            guide_category = st.selectbox("Save it under", all_categories, key="guide_cat")
            if st.button("📚 Build Study Guide", key="guide_build", type="primary",
                         disabled=len(picked_labels) < 2 or not guide_title.strip()):
                sections = []
                for label in picked_labels:
                    note = guide_labels[label]
                    body = _read_note(note["category"], note["filename"])
                    if body.strip():
                        sections.append((note["title"], body))
                if len(sections) < 2:
                    st.error("Couldn't read enough of those notes from disk.")
                else:
                    with st.spinner(f"Merging {len(sections)} notes with {selected_ollama}…"):
                        try:
                            guide = engine.synthesize_notes(
                                sections, config.STUDY_GUIDE_PROMPT, model_name=selected_ollama)
                        except Exception as exc:
                            guide = None
                            st.error(f"Study guide generation failed: {exc}")
                    if guide:
                        clean_title = guide_title.strip()
                        guide_dir = config.STORAGE_DIR / guide_category
                        guide_dir.mkdir(parents=True, exist_ok=True)
                        slug = storage.unique_slug(guide_dir, storage.slugify(clean_title))
                        target_dir = guide_dir / slug
                        target_dir.mkdir(parents=True, exist_ok=True)
                        sources = "\n".join(f"- {t}" for t, _ in sections)
                        document = (
                            f"# {clean_title}\n*Category: {guide_category}*\n"
                            f"*Built from {len(sections)} notes*\n\n{guide}\n\n---\n"
                            f"### 📎 Built From\n{sources}\n"
                        )
                        md_file = target_dir / NOTE_FILENAME
                        md_file.write_text(document, encoding="utf-8")
                        db.add_note(title=clean_title, category=guide_category,
                                    filename=f"{slug}/{NOTE_FILENAME}", template="Study Guide",
                                    tags="study-guide", word_count=len(document.split()))
                        row = db.get_note(guide_category, f"{slug}/{NOTE_FILENAME}")
                        storage.write_note_meta(
                            md_file, NOTE_FILENAME, title=clean_title, tags="study-guide",
                            template="Study Guide", word_count=len(document.split()),
                            created_at=row["created_at"] if row else None)
                        st.session_state["selected_file"] = md_file
                        st.session_state["flash"] = f'Built “{clean_title}”.'
                        st.rerun()

    # ================================ WORK ================================
    with tab_work:
        task_stats = db.action_item_stats()
        w1, w2, w3 = st.columns(3)
        w1.metric("Open", task_stats["open"])
        w2.metric("Completed", task_stats["done"])
        w3.metric("Total Tracked", task_stats["total"])

        st.markdown("#### ✅ Action Items")
        st.caption(
            "Pulled from the checkboxes in your notes. Ticking one here also ticks it in the "
            "note file itself, so the note stays the record of what's outstanding."
        )

        show_done = st.checkbox("Show completed items too", value=False, key="show_done_tasks")
        items = db.action_items(include_done=show_done)

        if not items:
            st.info(
                "No action items yet. Templates like **Meeting**, **One-on-One**, and "
                "**Client / Discovery Call** produce them automatically — or add "
                "`- [ ] Task` lines to any note yourself and rescan below."
            )
        else:
            by_note = {}
            for item in items:
                by_note.setdefault((item["category"], item["filename"]), []).append(item)

            for (category, filename), note_items in by_note.items():
                note_row = db.get_note(category, filename)
                heading = note_row["title"] if note_row else filename
                with st.container(border=True):
                    head_col, open_col = st.columns([5, 1])
                    head_col.markdown(f"**📄 {heading}** · {category}")
                    with open_col:
                        if st.button("Open →", key=f"task_open_{category}_{filename}",
                                     use_container_width=True):
                            st.session_state["selected_file"] = _note_path(category, filename)
                            st.rerun()
                    for item in note_items:
                        checked = st.checkbox(
                            item["text"], value=bool(item["done"]), key=f"task_{item['id']}",
                        )
                        meta_bits = []
                        if item["owner"]:
                            meta_bits.append(f"👤 {item['owner']}")
                        if item["due"]:
                            meta_bits.append(f"📅 {item['due']}")
                        if meta_bits:
                            st.caption(" · ".join(meta_bits))
                        if checked != bool(item["done"]):
                            if _complete_action_item(item, checked):
                                st.session_state["flash"] = (
                                    "Marked done." if checked else "Reopened."
                                )
                            else:
                                st.session_state["flash"] = (
                                    "That line has changed in the note — rescan to resync."
                                )
                            st.rerun()

        if st.button("🔄 Rescan all notes for action items", key="rescan_tasks",
                     help="Runs automatically at startup — use this after editing notes "
                          "outside the app in the same session."):
            st.session_state["flash"] = f"Rescanned {_resync_all_action_items()} note(s)."
            st.rerun()

        st.divider()
        st.markdown("#### ✉️ Draft a Follow-Up")
        st.caption(
            "Turn a meeting, interview, or networking note into a follow-up email you can "
            "edit and send — referencing what was actually discussed."
        )
        followup_notes = db.search("")
        if not followup_notes:
            st.info("Save a note first.")
        else:
            fu_labels = {f"{n['title']} — {n['category']}": n for n in followup_notes}
            fu_choice = st.selectbox("From note", list(fu_labels), key="fu_note")
            fu_tone = st.selectbox(
                "Tone", ["warm but professional", "brief and direct", "formal", "enthusiastic"],
                key="fu_tone",
            )
            if st.button("✉️ Draft Follow-Up", key="fu_generate"):
                note = fu_labels[fu_choice]
                body = _read_note(note["category"], note["filename"])
                if not body.strip():
                    st.error("That note's file couldn't be read.")
                else:
                    with st.spinner(f"Drafting with {selected_ollama}…"):
                        try:
                            st.session_state["followup_draft"] = engine.generate_followup(
                                body, tone=fu_tone, model_name=selected_ollama)
                            st.session_state["followup_for"] = note["title"]
                        except Exception as exc:
                            st.error(f"Drafting failed: {exc}")

            if st.session_state.get("followup_draft"):
                st.text_area(
                    f"Draft for “{st.session_state.get('followup_for', '')}” — edit before sending",
                    value=st.session_state["followup_draft"], height=280, key="fu_draft_box",
                )
                st.download_button(
                    "⬇️ Download draft (.txt)", data=st.session_state["fu_draft_box"],
                    file_name="follow_up.txt", mime="text/plain", key="fu_download",
                )
                st.caption("EchoPad never sends anything — copy it into your own email client.")

        st.divider()
        st.markdown("#### 🗓️ Weekly Digest")
        st.caption(
            "Summarize what you actually did over a period, across every note — useful for "
            "a status update, a standup, or a 1:1 agenda."
        )
        digest_days = st.selectbox("Period", [7, 14, 30], format_func=lambda d: f"Last {d} days",
                                   key="digest_days")
        if st.button("🗓️ Build Digest", key="digest_build"):
            cutoff = (date.today() - timedelta(days=int(digest_days))).isoformat()
            recent = [n for n in db.search("") if (n["created_at"] or "")[:10] >= cutoff]
            if not recent:
                st.warning(f"No notes saved in the last {digest_days} days.")
            else:
                sections = []
                for note in recent:
                    body = _read_note(note["category"], note["filename"])
                    if body.strip():
                        sections.append((f"{note['title']} ({note['created_at'][:10]})", body))
                with st.spinner(f"Summarizing {len(sections)} note(s) with {selected_ollama}…"):
                    try:
                        st.session_state["digest_text"] = engine.synthesize_notes(
                            sections, config.DIGEST_PROMPT, model_name=selected_ollama)
                        st.session_state["digest_count"] = len(sections)
                    except Exception as exc:
                        st.error(f"Digest generation failed: {exc}")

        if st.session_state.get("digest_text"):
            st.caption(f"From {st.session_state.get('digest_count', 0)} note(s):")
            st.markdown(st.session_state["digest_text"])
            st.download_button(
                "⬇️ Download digest (.md)", data=st.session_state["digest_text"],
                file_name="weekly_digest.md", mime="text/markdown", key="digest_download",
            )

    # ============================== SETTINGS ==============================
    with tab_settings:
        st.markdown("#### 📁 Categories")
        st.caption("Add your own categories beyond the built-ins. Built-in categories can't be removed; custom ones can be, once they're empty.")
        custom_categories = db.get_pref_json("custom_categories", default=[])
        col_cat1, col_cat2 = st.columns([3, 1])
        with col_cat1:
            new_category = st.text_input("New category name", key="new_category_input", label_visibility="collapsed", placeholder="e.g. Research")
        with col_cat2:
            if st.button("➕ Add", key="add_category_btn", use_container_width=True):
                name = new_category.strip()
                if not name:
                    st.toast("Enter a category name first.", icon="⚠️")
                elif name in all_categories:
                    st.toast(f'"{name}" already exists.', icon="⚠️")
                else:
                    custom_categories.append(name)
                    db.set_pref_json("custom_categories", custom_categories)
                    del st.session_state["new_category_input"]
                    st.session_state["flash"] = f'Added category "{name}".'
                    st.rerun()

        if custom_categories:
            note_counts = db.counts_by_category()
            for cat in custom_categories:
                c1, c2 = st.columns([4, 1])
                c1.write(f"🏷️ {cat} — {note_counts.get(cat, 0)} note(s)")
                with c2:
                    if note_counts.get(cat, 0) == 0:
                        if st.button("Remove", key=f"remove_cat_{cat}", use_container_width=True):
                            custom_categories.remove(cat)
                            db.set_pref_json("custom_categories", custom_categories)
                            st.session_state["flash"] = f'Removed category "{cat}".'
                            st.rerun()
                    else:
                        st.caption("in use")

        st.divider()
        st.markdown("#### 📝 Prompt Templates")
        st.caption("Built-in templates are read-only. Add your own — the prompt must include a `{transcript}` placeholder.")
        custom_templates = db.get_pref_json("custom_templates", default={})

        with st.expander("➕ Add a custom template"):
            tpl_name = st.text_input("Template name", key="new_tpl_name", placeholder="e.g. Study Group Recap")
            tpl_body = st.text_area(
                "Prompt", key="new_tpl_body", height=180,
                placeholder="You are ... Format the transcript into ...\n\nTranscript:\n{transcript}",
            )
            if st.button("Save Template", key="save_tpl_btn"):
                name = tpl_name.strip()
                if not name or not tpl_body.strip():
                    st.toast("Give the template a name and a prompt.", icon="⚠️")
                elif "{transcript}" not in tpl_body:
                    st.toast('The prompt must include a "{transcript}" placeholder.', icon="⚠️")
                elif name in config.TEMPLATES:
                    st.toast(f'"{name}" is a built-in template name — pick a different one.', icon="⚠️")
                else:
                    custom_templates[name] = tpl_body
                    db.set_pref_json("custom_templates", custom_templates)
                    del st.session_state["new_tpl_name"]
                    del st.session_state["new_tpl_body"]
                    st.session_state["flash"] = f'Saved template "{name}".'
                    st.rerun()

        if custom_templates:
            for name in list(custom_templates.keys()):
                c1, c2 = st.columns([4, 1])
                c1.write(f"📝 {name}")
                with c2:
                    if st.button("Delete", key=f"del_tpl_{name}", use_container_width=True):
                        del custom_templates[name]
                        db.set_pref_json("custom_templates", custom_templates)
                        st.session_state["flash"] = f'Deleted template "{name}".'
                        st.rerun()

        st.divider()
        st.markdown("#### 🎛️ Default Models")
        st.caption("Saved as your default for next time — you can still override per-note in the sidebar.")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            new_default_whisper = st.selectbox(
                "Default Whisper Model", config.WHISPER_MODELS,
                index=_safe_index(config.WHISPER_MODELS, default_whisper, fallback=1),
                key="settings_default_whisper",
            )
        with col_m2:
            new_default_ollama = st.selectbox(
                "Default Ollama Model", all_ollama_models,
                index=_safe_index(all_ollama_models, default_ollama, fallback=0),
                key="settings_default_ollama",
            )
        if st.button("💾 Save as Default", key="save_defaults_btn"):
            db.set_pref("default_whisper_model", new_default_whisper)
            db.set_pref("default_ollama_model", new_default_ollama)
            st.session_state["flash"] = "Defaults saved."
            st.rerun()

        st.caption("Add a custom Ollama model name (e.g. one you've pulled locally that isn't listed above):")
        col_om1, col_om2 = st.columns([3, 1])
        with col_om1:
            new_ollama_name = st.text_input("Custom Ollama model", key="new_ollama_model_input", label_visibility="collapsed", placeholder="e.g. mistral, phi3")
        with col_om2:
            if st.button("➕ Add", key="add_ollama_model_btn", use_container_width=True):
                name = new_ollama_name.strip()
                custom_models = db.get_pref_json("custom_ollama_models", default=[])
                if not name:
                    st.toast("Enter a model name first.", icon="⚠️")
                elif name in all_ollama_models:
                    st.toast(f'"{name}" is already available.', icon="⚠️")
                else:
                    custom_models.append(name)
                    db.set_pref_json("custom_ollama_models", custom_models)
                    del st.session_state["new_ollama_model_input"]
                    st.session_state["flash"] = f'Added "{name}" to your Ollama model list.'
                    st.rerun()

        st.divider()
        st.markdown("#### ☁️ Storage Location & Cloud Sync")
        st.caption("Where your notes and recordings are kept on this computer.")
        st.code(str(config.STORAGE_DIR.resolve()), language=None)

        if config.storage_dir_is_pinned():
            st.info(
                "The location is set by the `ECHOPAD_STORAGE_DIR` environment variable "
                "(this is how the Docker one-click launcher runs). Change it in your "
                "`.env` or `docker-compose.yml` rather than here."
            )
        else:
            providers = storage.detect_providers()
            options = ["This computer only (default folder)"]
            targets = [Path("./notes").resolve()]
            for provider in providers:
                options.append(f"{provider['label']} — synced to the cloud")
                targets.append(storage.library_path_for(provider["path"]))
            options.append("Custom folder…")
            targets.append(None)

            if providers:
                st.caption(
                    "Because EchoPad stores plain files, pointing it at a folder your cloud app "
                    "already syncs gives you cross-device access, version history, and off-device "
                    "backup — with no sign-in, API keys, or account access needed here. "
                    "Notes kept in a synced folder do leave this machine and reach that provider; "
                    "the default folder stays fully local."
                )
            else:
                st.caption(
                    "No OneDrive, Google Drive, iCloud, or Dropbox folder was detected on this "
                    "computer. Install the provider's desktop sync app (e.g. OneDrive, or Google "
                    "Drive for Desktop), then reopen this tab — or point EchoPad at any folder "
                    "with the custom option."
                )

            picked = st.radio("Keep my notes in:", options, index=0, key="storage_choice")
            picked_target = targets[options.index(picked)]

            if picked_target is None:
                custom_path = st.text_input(
                    "Folder path", key="custom_storage_path",
                    placeholder=r"e.g. D:\Dropbox\EchoPad  or  /Users/you/Documents/EchoPad",
                )
                picked_target = Path(custom_path.strip()).expanduser() if custom_path.strip() else None
                if picked_target:
                    st.caption(
                        "Pick a folder used only for EchoPad. Pointing at a large shared root "
                        "(your whole OneDrive, say) would make EchoPad scan everything in it."
                    )

            if picked_target:
                already_here = False
                try:
                    already_here = picked_target.resolve() == config.STORAGE_DIR.resolve()
                except OSError:
                    pass
                st.caption("Notes would be stored in:")
                st.code(str(picked_target), language=None)
                if already_here:
                    st.caption("✅ That's already your current location.")
                elif st.button("📂 Use This Location", key="use_storage_btn"):
                    _confirm_storage_dialog(picked_target, sum(db.counts_by_category().values()))

            st.caption(
                "Each note folder carries its own `meta.json` with its title and tags, so those "
                "travel with the note when it moves or syncs to another computer. The search "
                "index itself stays on this machine and rebuilds from those files, since sync "
                "clients can corrupt a live database. App preferences remain per-computer."
            )

        st.divider()
        st.markdown("#### 🎨 Display")
        compact_mode = db.get_pref("compact_mode", default="false") == "true"
        new_compact = st.checkbox("Compact mode (tighter spacing)", value=compact_mode, key="compact_mode_checkbox")
        if new_compact != compact_mode:
            db.set_pref("compact_mode", "true" if new_compact else "false")
            st.rerun()
        st.caption("Light/dark theme can be switched from the ⋮ menu in the top-right corner.")

        st.divider()
        st.markdown("#### 💾 Backup & Export")
        st.caption("Download every note, recording, and tag as a single .zip — handy before reinstalling, switching computers, or just for peace of mind.")
        if st.button("📦 Prepare Backup", key="prepare_backup_btn"):
            st.session_state["backup_zip"] = _build_backup_zip()
        if "backup_zip" in st.session_state:
            st.download_button(
                "⬇️ Download All Notes (.zip)", data=st.session_state["backup_zip"],
                file_name="echopad_backup.zip", mime="application/zip", key="download_backup_btn",
            )

        st.divider()
        st.markdown("#### ℹ️ About")
        st.caption(f"EchoPad v{APP_VERSION} · 100% local & private · [GitHub](https://github.com/br24563/Echo-pad)")
