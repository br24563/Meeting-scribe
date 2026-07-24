import os
import tempfile
import streamlit as st
from pathlib import Path
import config
import engine

st.set_page_config(page_title="EchoPad", page_icon="🎙️", layout="wide")

if not engine.check_ollama_status():
    st.error("⚠️ **Ollama is not running!** Please start Ollama (`ollama serve`) and refresh.")
    st.stop()

st.title("🎙️ EchoPad — AI Voice Notebook")
st.caption("Study smarter. Interview sharper. Network better. 100% local and private.")

# --- SIDEBAR CONFIG ---
st.sidebar.header("⚙️ Settings & Pipeline")
selected_whisper = st.sidebar.selectbox("Whisper Model", config.WHISPER_MODELS, index=1)
selected_ollama = st.sidebar.selectbox("Ollama Model", config.OLLAMA_MODELS, index=0)
translate_option = st.sidebar.checkbox("🌐 Translate to English", value=False)

st.sidebar.divider()

# --- FULL-TEXT SEARCH ---
st.sidebar.header("🔍 Full-Text Search")
search_query = st.sidebar.text_input("Search notes...", placeholder="e.g. latency, vector, Q3")

search_results = engine.search_notes(search_query) if search_query else []

if search_query:
    st.sidebar.caption(f"Found {len(search_results)} result(s)")
    for res in search_results:
        if st.sidebar.button(f"📄 {res['name']}", key=str(res['path'])):
            st.session_state["selected_file"] = res['path']

st.sidebar.divider()
st.sidebar.header("📁 Subsections")
selected_category = st.sidebar.selectbox("Select Category", config.SUBSECTIONS)
cat_dir = config.STORAGE_DIR / selected_category
cat_dir.mkdir(exist_ok=True)

existing_notes = [f.name for f in cat_dir.glob("*.md")]
selected_note_name = st.sidebar.selectbox("📖 Saved Notes", ["None"] + existing_notes)

# Override selection if search result clicked
active_file = st.session_state.get("selected_file", None)
if selected_note_name != "None" and not active_file:
    active_file = cat_dir / selected_note_name

# --- MAIN WORKSPACE ---
if active_file and active_file.exists():
    st.subheader(f"📖 Reading: {active_file.stem.replace('_', ' ').title()}")
    
    # Audio Playback
    audio_file_path = active_file.with_suffix(".wav")
    if audio_file_path.exists():
        st.audio(str(audio_file_path))
        
    with open(active_file, "r", encoding="utf-8") as f:
        note_content = f.read()

    # Interactive In-App Editor
    with st.expander("✏️ Edit Note Content", expanded=False):
        edited_content = st.text_area("Edit Markdown", value=note_content, height=300)
        if st.button("💾 Save Changes"):
            with open(active_file, "w", encoding="utf-8") as f:
                f.write(edited_content)
            st.success("Note updated successfully!")
            st.rerun()

    st.markdown(edited_content if 'edited_content' in locals() else note_content)

    # Multi-Format Export Buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📥 Download .MD", data=note_content, file_name=active_file.name, mime="text/markdown")
    with col2:
        html_data = engine.convert_md_to_html(note_content)
        st.download_button("🌐 Download .HTML", data=html_data, file_name=f"{active_file.stem}.html", mime="text/html")
    with col3:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = os.path.join(tmp_dir, f"{active_file.stem}.pdf")
            engine.convert_md_to_pdf(note_content, pdf_path)
            with open(pdf_path, "rb") as pf:
                pdf_bytes = pf.read()
        st.download_button("📄 Download .PDF", data=pdf_bytes, file_name=f"{active_file.stem}.pdf", mime="application/pdf")

    if st.button("❌ Close Note"):
        st.session_state["selected_file"] = None
        st.rerun()

else:
    st.subheader("🆕 Record or Upload Voice Note")
    title = st.text_input(
        "Note Title",
        placeholder="e.g. Organic Chemistry Midterm Review, or Interview Debrief — Acme Corp",
    )
    selected_template = st.selectbox("Select Prompt Template", list(config.TEMPLATES.keys()))

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
                
                transcript = engine.transcribe_audio(
                    audio_bytes, 
                    model_size=selected_whisper, 
                    translate=translate_option
                )

                st.write(f"🧠 Summarizing with {selected_ollama} ({selected_template} Template)...")
                summary = engine.generate_summary(transcript, template_key=selected_template, model_name=selected_ollama)
                status.update(label="Complete!", state="complete", expanded=False)

            full_document = f"# {title}\n*Category: {selected_category}*\n\n{summary}\n\n---\n### 📝 Raw Transcript\n{transcript}"
            base_filename = title.lower().strip().replace(' ', '_')
            safe_filename = base_filename
            suffix = 1
            while (cat_dir / f"{safe_filename}.md").exists():
                suffix += 1
                safe_filename = f"{base_filename}_{suffix}"

            # Save Markdown File
            md_path = cat_dir / f"{safe_filename}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(full_document)

            # Save Audio File for Playback
            wav_path = cat_dir / f"{safe_filename}.wav"
            with open(wav_path, "wb") as f:
                f.write(audio_bytes)

            st.success(f"Saved note and audio to `{selected_category}/{safe_filename}`!")
            st.markdown(full_document)
