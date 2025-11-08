# tts_google.py – Google Cloud Text-to-Speech（TTS）対応版（jaはcalm＋固定ボイス）
from google.cloud import texttospeech
from pathlib import Path
import os, random

# 各言語のデフォルト音声（安全フォールバック）
VOICE_MAP = {
    "en": "en-US-Neural2-D",
    "ja": "ja-JP-Neural2-C",
    "ko": "ko-KR-Neural2-B",
    "pt": "pt-BR-Neural2-B",
    "id": "id-ID-Neural2-A",
}

# スタイルの軽量プリセット
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
    """
    ボイス決定の優先順位：
      1) GOOGLE_VOICE_FIXED_JA / GOOGLE_VOICE_FIXED_{LANG} / GOOGLE_VOICE_FIXED
      2) GOOGLE_VOICE_POOL_{LANG} / GOOGLE_VOICE_POOL（プールから抽選）
      3) VOICE_MAP 既定
    """
    key_lang = (lang or "").strip().lower()
    lang_tag = key_lang.upper()

    # ① 固定指定（推奨：日本語はこれで1つに固定）
    fixed = (
        os.getenv(f"GOOGLE_VOICE_FIXED_{lang_tag}", "").strip()
        or (os.getenv("GOOGLE_VOICE_FIXED_JA", "").strip() if lang_tag == "JA" else "")
        or os.getenv("GOOGLE_VOICE_FIXED", "").strip()
    )
    if fixed:
        return fixed

    # ② プール抽選
    pool_lang = _parse_pool(os.getenv(f"GOOGLE_VOICE_POOL_{lang_tag}", ""))
    pool_all  = _parse_pool(os.getenv("GOOGLE_VOICE_POOL", ""))

    seed = os.getenv("GOOGLE_VOICE_SEED", "").strip()
    if seed:
        try:
            random.seed(int(seed))
        except Exception:
            random.seed(seed)

    if pool_lang:
        return random.choice(pool_lang)
    if pool_all:
        return random.choice(pool_all)

    # ③ 既定
    return VOICE_MAP.get(lang, "en-US-Neural2-D")

def _style_params(style: str) -> dict:
    base = _STYLE_PRESET.get((style or "neutral").lower(), _STYLE_PRESET["neutral"]).copy()
    # 環境変数で上書き（数値に変換できる場合のみ）
    try:
        if os.getenv("GOOGLE_TTS_RATE"):   base["speaking_rate"]  = float(os.getenv("GOOGLE_TTS_RATE"))
        if os.getenv("GOOGLE_TTS_PITCH"):  base["pitch"]          = float(os.getenv("GOOGLE_TTS_PITCH"))
        if os.getenv("GOOGLE_TTS_VOL_DB"): base["volume_gain_db"] = float(os.getenv("GOOGLE_TTS_VOL_DB"))
    except ValueError:
        pass
    return base

def speak(lang: str, speaker: str, text: str, out_path: Path, style: str = "neutral"):
    """
    main.py と同じシグネチャ。
    日本語だけは「calm」＋固定ボイスを強制（エラー回避重視）。
    他言語は従来ロジック（style引数を尊重）。
    """
    client = texttospeech.TextToSpeechClient()

    # --- 日本語は常に calm & 固定ボイス ---
    if (lang or "").lower() == "ja":
        voice_name = _pick_voice_name("ja") or "ja-JP-Neural2-C"
        forced_style = "calm"
        st = _style_params(forced_style)
    else:
        voice_name = _pick_voice_name(lang)
        st = _style_params(style)

    # 言語コードは voice_name から推定（"en-US-Neural2-D" → "en-US"）
    parts = voice_name.split("-")
    lang_code = "-".join(parts[:2]) if len(parts) >= 2 else ("ja-JP" if (lang or "").lower()=="ja" else "en-US")

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice_name)

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV
        sample_rate_hertz=int(os.getenv("GOOGLE_TTS_SAMPLE_RATE", "24000")),
        speaking_rate=st.get("speaking_rate", 1.0),
        pitch=st.get("pitch", 0.0),
        volume_gain_db=st.get("volume_gain_db", 0.0),
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(response.audio_content)