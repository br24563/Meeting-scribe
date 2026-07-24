import ollama
from faster_whisper import WhisperModel

# Initialize Whisper model locally (loads once in memory)
@st.cache_resource if 'st' in globals() else lambda x: x
def load_whisper():
    return WhisperModel("base", device="cpu", compute_type="int8")

def transcribe(audio_bytes) -> str:
    # Save audio temporarily for Whisper
    with open("temp_audio.wav", "wb") as f:
        f.write(audio_bytes.read())
        
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe("temp_audio.wav")
    return " ".join([segment.text.strip() for segment in segments])

def generate_summary(transcript: str) -> str:
    prompt = f"""
    You are an expert note-taker. Summarize this audio transcript into clean Markdown.
    
    Format:
    ## 🎯 Core Takeaways
    ## 📌 Key Discussion Points
    ## 📋 Action Items / Next Steps
    
    Transcript:
    {transcript}
    """
    response = ollama.generate(model="llama3.2", prompt=prompt)
    return response['response']
