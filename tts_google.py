# tts_google.py – Google Cloud Text-to-Speech（TTS）対応版
from google.cloud import texttospeech
from pathlib import Path
import os, random

VOICE_MAP = {
    "en": "en-US-Neural2-D",
    "ja": "ja-JP-Neural2-C",
    "ko": "ko-KR-Neural2-B",
    "pt": "pt-BR-Neural2-B",
    "id": "id-ID-Neural2-A",
}

_STYLE_PRESET = {
    "neutral":   dict(speaking_rate=1.00, pitch=0.0,  volume_gain_db=0.0),
    "calm":      dict(speaking_rate=0.95, pitch=-1.0, volume_gain_db=0.0),
    "energetic": dict(speaking_rate=1.08, pitch=+2.0, volume_gain_db=0.0),
    "serious":   dict(speaking_rate=0.98, pitch=-0.5, volume_gain_db=0.0),
}

def _parse_pool(env_val: str) -> list[str]:
    if not env_val:
        return []
    return [x.strip() for x in env_val.split(",") if x.strip()]

def _pick_voice_name(lang: str) -> str:
    key_lang = (lang or "").strip().lower()
    lang_tag = key_lang.upper()
    pool_lang = _parse_pool(os.getenv(f"GOOGLE_VOICE_POOL_{lang_tag}", ""))
    pool_all  = _parse_pool(os.getenv("GOOGLE_VOICE_POOL", ""))

    seed = os.getenv("GOOGLE_VOICE_SEED", "").strip()
    if seed:
        try: random.seed(int(seed))
        except Exception: random.seed(seed)

    if pool_lang: return random.choice(pool_lang)
    if pool_all:  return random.choice(pool_all)
    return VOICE_MAP.get(lang, "en-US-Neural2-D")

def _style_params(style: str) -> dict:
    base = _STYLE_PRESET.get((style or "neutral").lower(), _STYLE_PRESET["neutral"]).copy()
    try:
        if os.getenv("GOOGLE_TTS_RATE"):   base["speaking_rate"]  = float(os.getenv("GOOGLE_TTS_RATE"))
        if os.getenv("GOOGLE_TTS_PITCH"):  base["pitch"]          = float(os.getenv("GOOGLE_TTS_PITCH"))
        if os.getenv("GOOGLE_TTS_VOL_DB"): base["volume_gain_db"] = float(os.getenv("GOOGLE_TTS_VOL_DB"))
    except ValueError:
        pass
    return base

def speak(lang: str, speaker: str, text: str, out_path: Path, style: str = "neutral"):
    client = texttospeech.TextToSpeechClient()

    voice_name = _pick_voice_name(lang)
    parts = voice_name.split("-")
    lang_code = "-".join(parts[:2]) if len(parts) >= 2 else "en-US"

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice_name)

    st = _style_params(style)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV
        sample_rate_hertz=int(os.getenv("GOOGLE_TTS_SAMPLE_RATE", "24000")),
        speaking_rate=st.get("speaking_rate", 1.0),
        pitch=st.get("pitch", 0.0),
        volume_gain_db=st.get("volume_gain_db", 0.0),
    )

    response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(response.audio_content)