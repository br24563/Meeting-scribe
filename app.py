import streamlit as st
import os
from pathlib import Path
from engine import transcribe, generate_summary

st.set_page_config(page_title="EchoPad", page_icon="🎙️", layout="wide")

NOTES_DIR = Path("./notes")
NOTES_DIR.mkdir(exist_ok=True)

st.title("🎙️ EchoPad — AI Voice Notebook")

# --- SIDEBAR: CATEGORY & PAST NOTES BROWSER ---
st.sidebar.header("📁 Subsections & Notes")

# Pre-defined subsections or create a new one
subsections = ["General", "Lectures", "Meetings", "Brainstorming"]
selected_category = st.sidebar.selectbox("Select Subsection", subsections)

cat_dir = NOTES_DIR / selected_category
cat_dir.mkdir(exist_ok=True)

# List existing notes in selected subsection
existing_notes = [f.name for f in cat_dir.glob("*.md")]
selected_note = st.sidebar.selectbox("View Saved Notes", ["None"] + existing_notes)

# --- MAIN WORKSPACE ---
if selected_note != "None":
    # VIEW MODE
    st.subheader(f"📖 Reading: {selected_note}")
    with open(cat_dir / selected_note, "r") as f:
        st.markdown(f.read())
else:
    # RECORDING MODE
    st.subheader("🆕 Create New Voice Note")
    
    title = st.text_input("Recording Title", placeholder="e.g., Sprint Planning or Lecture 4")
    
    # Built-in live browser microphone recorder
    audio_data = st.audio_input("Click the microphone to start recording")
    
    if audio_data and title:
        if st.button("✨ Transcribe & Summarize", type="primary"):
            with st.status("Processing Audio...", expanded=True) as status:
                st.write("👂 Transcribing audio with Whisper...")
                transcript = transcribe(audio_data)
                
                st.write("🧠 Summarizing with Llama 3.2...")
                summary = generate_summary(transcript)
                
                status.update(label="Complete!", state="complete", expanded=False)
            
            # Combine into Markdown content
            full_content = f"# {title}\n*Category: {selected_category}*\n\n{summary}\n\n---\n### 📝 Raw Transcript\n{transcript}"
            
            # Save file
            filename = f"{title.lower().replace(' ', '_')}.md"
            with open(cat_dir / filename, "w") as f:
                f.write(full_content)
                
            st.success(f"Saved to `{selected_category}/{filename}`!")
            st.markdown(full_content)
