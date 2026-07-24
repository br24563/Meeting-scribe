import streamlit as st
from pathlib import Path
import config
import engine

# --- PAGE CONFIG ---
st.set_page_config(page_title="EchoPad", page_icon="🎙️", layout="wide")

# --- OLLAMA HEALTH CHECK ---
if not engine.check_ollama_status():
    st.error("⚠️ **Ollama is not running!** Please start Ollama in your terminal (`ollama serve`) and refresh this page.")
    st.stop()

st.title("🎙️ EchoPad — AI Voice Notebook")

# --- SIDEBAR: SETTINGS & NAVIGATION ---
st.sidebar.header("⚙️ Model Settings")
selected_whisper = st.sidebar.selectbox("Whisper Model (STT)", config.WHISPER_MODELS, index=1)
selected_ollama = st.sidebar.selectbox("Ollama Model (LLM)", config.OLLAMA_MODELS, index=0)

st.sidebar.divider()
st.sidebar.header("📁 Subsections")

selected_category = st.sidebar.selectbox("Select Subsection", config.SUBSECTIONS)
cat_dir = config.STORAGE_DIR / selected_category
cat_dir.mkdir(exist_ok=True)

existing_notes = [f.name for f in cat_dir.glob("*.md")]
selected_note = st.sidebar.selectbox("📖 View Saved Notes", ["None"] + existing_notes)

# --- MAIN WORKSPACE ---
if selected_note != "None":
    # VIEW MODE
    note_path = cat_dir / selected_note
    st.subheader(f"📖 Note: {selected_note.replace('.md', '').replace('_', ' ').title()}")
    
    with open(note_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    st.markdown(content)
    
    st.download_button(
        label="📥 Download Markdown Note",
        data=content,
        file_name=selected_note,
        mime="text/markdown"
    )

else:
    # RECORD MODE
    st.subheader("🆕 Create New Voice Note")
    title = st.text_input("Recording Title", placeholder="e.g., Sprint Planning or Q3 Roadmap")
    
    # Browser audio microphone widget
    audio_data = st.audio_input("Click to start recording")

    if audio_data and title:
        if st.button("✨ Transcribe & Summarize", type="primary"):
            with st.status("Processing Audio Locally...", expanded=True) as status:
                st.write("👂 Transcribing audio with Whisper...")
                transcript = engine.transcribe_audio(audio_data, model_size=selected_whisper)
                
                st.write(f"🧠 Summarizing with {selected_ollama}...")
                summary = engine.generate_summary(transcript, model_name=selected_ollama)
                
                status.update(label="Complete!", state="complete", expanded=False)

            # Build full Notion-style document
            full_document = f"# {title}\n*Category: {selected_category}*\n\n{summary}\n\n---\n### 📝 Raw Transcript\n{transcript}"
            
            # Save file locally
            safe_filename = f"{title.lower().strip().replace(' ', '_')}.md"
            saved_path = cat_dir / safe_filename
            with open(saved_path, "w", encoding="utf-8") as f:
                f.write(full_document)

            st.success(f"Saved to `{selected_category}/{safe_filename}`!")
            st.markdown(full_document)
            
            st.download_button(
                label="📥 Download Markdown Note",
                data=full_document,
                file_name=safe_filename,
                mime="text/markdown"
            )ategory}/{filename}`!")
            st.markdown(full_content)
