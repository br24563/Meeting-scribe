import io
import os
import shutil
import tempfile
import zipfile
import streamlit as st
from pathlib import Path
import config
import db
import engine
import storage

APP_VERSION = "0.3.0"
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
    db.delete_note(category, filename)


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
            st.session_state["flash"] = "Note updated successfully."
            st.rerun()

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
    tab_dashboard, tab_new_note, tab_settings = st.tabs(["🏠 Dashboard", "🎙️ New Note", "⚙️ Settings"])

    # ============================== DASHBOARD ==============================
    with tab_dashboard:
        counts = db.counts_by_category()
        total_notes = sum(counts.values())
        if total_notes:
            # Only show categories that actually have notes, busiest first — capped so the
            # row stays readable even if the user has added many custom categories.
            active_categories = sorted((c for c in all_categories if counts.get(c, 0) > 0), key=lambda c: -counts[c])
            shown_categories = active_categories[:5]
            stat_cols = st.columns(len(shown_categories) + 2)
            stat_cols[0].metric("Total Notes", total_notes)
            stat_cols[1].metric("Words Captured", f"{db.total_word_count():,}")
            for col, cat in zip(stat_cols[2:], shown_categories):
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
        selected_template = st.selectbox("Select Prompt Template", list(all_templates.keys()))
        note_tags = st.text_input("🏷️ Tags (comma-separated, optional)", placeholder="e.g. midterm, chapter-4, orgo")

        tab_record, tab_upload = st.tabs(["🎙️ Live Mic Record", "📁 Upload Audio File"])
        audio_source = None

        with tab_record:
            rec_data = st.audio_input("Record live from browser mic")
            if rec_data:
                audio_source = rec_data

        with tab_upload:
            up_data = st.file_uploader("Upload audio file", type=["mp3", "m4a", "wav"])
            if up_data:
                audio_source = up_data

        if not title:
            st.info("👆 Give your note a title to get started.")
        elif not audio_source:
            st.info("🎙️ Record from your mic or upload a file above to continue.")

        if audio_source and title:
            st.caption("First-time use of a Whisper model size downloads it locally — this only happens once.")
            if st.button("✨ Process & Generate Note", type="primary"):
                with st.status("Processing Audio...", expanded=True) as status:
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

                    st.write(f"🧠 Summarizing with {selected_ollama} ({selected_template} Template)...")
                    template_text = all_templates.get(selected_template, config.TEMPLATES["Meeting"])
                    summary = engine.generate_summary(transcript, template=template_text, model_name=selected_ollama)
                    status.update(label="Complete!", state="complete", expanded=False)

                full_document = f"# {title}\n*Category: {selected_category}*\n\n{summary}\n\n---\n### 📝 Raw Transcript\n{transcript}"

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

                # Save Audio File for Playback
                wav_path = note_dir / AUDIO_FILENAME
                with open(wav_path, "wb") as f:
                    f.write(audio_bytes)

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

                st.success(f"Saved note and audio to `{selected_category}/{safe_slug}/`!")
                st.markdown(full_document)

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
