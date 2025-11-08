# tts_google.py – Google Cloud Text-to-Speech（TTS）対応版
# 目的：
#  - 日本語（ja）は動画ごとに男女声を交互（Neural2-C ↔ Neural2-B）
#  - 同一動画内では必ず同じ声（混在しない）
#  - 日本語のスタイルは常に "calm"
#  - 環境変数で固定指定があれば最優先（GOOGLE_VOICE_FIXED_JA / GOOGLE_VOICE_FIXED）
#  - 他言語は従来ロジック（固定 > プール > 既定）

from google.cloud import texttospeech
from pathlib import Path
import os, hashlib
from typing import List, Dict

# 各言語のデフォルト音声（安全フォールバック）
VOICE_MAP: Dict[str, str] = {
    "en": "en-US-Neural2-D",
    "ja": "ja-JP-Neural2-C",  # 既定はC（動画単位でBと交互）
    "ko": "ko-KR-Neural2-B",
    "pt": "pt-BR-Neural2-B",
    "id": "id-ID-Neural2-A",
}

# スタイルの軽量プリセット
_STYLE_PRESET: Dict[str, dict] = {
    "neutral":   dict(speaking_rate=1.00, pitch=0.0,  volume_gain_db=0.0),
    "calm":      dict(speaking_rate=0.95, pitch=-1.0, volume_gain_db=0.0),
    "energetic": dict(speaking_rate=1.08, pitch=+2.0, volume_gain_db=0.0),
    "serious":   dict(speaking_rate=0.98, pitch=-0.5, volume_gain_db=0.0),
}

def _parse_pool(env_val: str) -> List[str]:
    if not env_val:
        return []
    return [x.strip() for x in env_val.split(",") if x.strip()]

def _run_key() -> str:
    """
    動画“単位”で安定したキーを得る。
    優先順位: 明示キー > GitHub Run ID > SHA > フォールバック
    - RUN_STABLE_KEY     : 手動で固定したいときに指定（例: acc名＋日付 など）
    - GITHUB_RUN_ID      : Actions 実行ごとに一意
    - GITHUB_SHA         : 同じコミットで再実行時も一意
    """
    return (
        os.getenv("RUN_STABLE_KEY")
        or os.getenv("GITHUB_RUN_ID")
        or os.getenv("GITHUB_SHA")
        or "0"
    )

def _pick_ja_voice_per_video() -> str:
    """
    日本語のボイス決定。
    - 固定指定があれば最優先（GOOGLE_VOICE_FIXED_JA / GOOGLE_VOICE_FIXED）
    - それ以外は動画ごとに C ↔ B を交互（RUN_STABLE_KEY / GITHUB_RUN_ID に基づく）
    """
    fixed = (
        os.getenv("GOOGLE_VOICE_FIXED_JA", "").strip()
        or os.getenv("GOOGLE_VOICE_FIXED", "").strip()
    )
    if fixed:
        return fixed

    h = int(hashlib.md5(_run_key().encode()).hexdigest(), 16)
    # 偶数 → C（女性寄り）、奇数 → B（男性寄り）
    return "ja-JP-Neural2-C" if (h % 2 == 0) else "ja-JP-Neural2-B"

def _pick_voice_name(lang: str) -> str:
    """
    ボイス決定の優先順位：
      * 日本語: 固定指定 > 交互ロジック > 既定
      * 他言語: GOOGLE_VOICE_FIXED_{LANG}/GOOGLE_VOICE_FIXED > プール > 既定
    """
    key_lang = (lang or "").strip().lower()
    lang_tag = key_lang.upper()

    if key_lang == "ja":
        return _pick_ja_voice_per_video()

    fixed = (
        os.getenv(f"GOOGLE_VOICE_FIXED_{lang_tag}", "").strip()
        or os.getenv("GOOGLE_VOICE_FIXED", "").strip()
    )
    if fixed:
        return fixed

    pool_lang = _parse_pool(os.getenv(f"GOOGLE_VOICE_POOL_{lang_tag}", ""))
    pool_all  = _parse_pool(os.getenv("GOOGLE_VOICE_POOL", ""))
    if pool_lang:
        return pool_lang[0]  # 安定のため抽選せず先頭を使用（混在回避）
    if pool_all:
        return pool_all[0]
    return VOICE_MAP.get(key_lang, "en-US-Neural2-D")

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
    - 日本語: calm を強制 + 動画単位で B/C 切替。動画内は不変。
    - 他言語: 引数style/環境変数に従う（固定/プール/既定）。
    """
    client = texttospeech.TextToSpeechClient()

    if (lang or "").lower() == "ja":
        voice_name = _pick_ja_voice_per_video()
        st = _style_params("calm")
    else:
        voice_name = _pick_voice_name(lang)
        st = _style_params(style)

    # 言語コードは voice_name から推定（"en-US-Neural2-D" → "en-US"）
    parts = voice_name.split("-")
    lang_code = "-".join(parts[:2]) if len(parts) >= 2 else ("ja-JP" if (lang or "").lower() == "ja" else "en-US")

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