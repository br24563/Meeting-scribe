import os
import ollama
from faster_whisper import WhisperModel
import config

def check_ollama_status() -> bool:
    """Verify if local Ollama engine is active and reachable."""
    try:
        ollama.list()
        return True
    except Exception:
        return False

def transcribe_audio(audio_bytes, model_size: str = config.DEFAULT_WHISPER_MODEL) -> str:
    """Transcribe raw browser audio input using faster-whisper locally."""
    temp_path = "temp_recording.wav"
    
    # Save temporary audio binary from browser
    with open(temp_path, "wb") as f:
        f.write(audio_bytes.read())

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(temp_path, beam_size=5)
        full_transcript = " ".join([segment.text.strip() for segment in segments])
    finally:
        # Guarantee cleanup of local temporary audio file
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return full_transcript

def generate_summary(transcript: str, model_name: str = config.DEFAULT_OLLAMA_MODEL) -> str:
    """Generate structured Notion-style Markdown note using local Ollama model."""
    prompt = config.NOTION_PROMPT.format(transcript=transcript)
    response = ollama.generate(model=model_name, prompt=prompt)
    return response["response"]
