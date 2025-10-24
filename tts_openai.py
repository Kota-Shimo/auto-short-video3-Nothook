"""OpenAI TTS wrapper – language-aware & two-speaker support with simple style control."""

import re
from pathlib import Path
from openai import OpenAI
from config import OPENAI_API_KEY, VOICE_MAP

client = OpenAI(api_key=OPENAI_API_KEY)

# VOICE_MAP に無い言語のフォールバック（Alice, Bob）
FALLBACK_VOICES = ("alloy", "echo")


def _clean_for_tts(text: str, lang: str) -> str:
    """
    音声合成前の整形：
    - 冒頭の話者ラベル（Alice:/Bob:/N:）を除去
    - 余分な空白・改行を整理
    - 日本語はローマ字/英単語・一部記号を除去して誤読を抑制
    """
    t = re.sub(r"^[A-Za-z]+:\s*", "", text)  # Alice:/Bob:/N: を削除
    t = re.sub(r"\s+", " ", t).strip()

    if lang == "ja":
        t = re.sub(r"[A-Za-z]+", "", t)      # ローマ字/英単語の排除（数字は残す）
        t = re.sub(r"[#\"'※＊*~`]", "", t)   # 記号の整理
        t = re.sub(r"\s+", " ", t).strip()

    return t or ("。" if lang == "ja" else ".")


def _apply_style(text: str, lang: str, style: str) -> str:
    """
    句読点で“抑揚”を軽く誘導する簡易スタイル。
    - energetic: 感嘆系で勢いをつける
    - calm     : 句点で落ち着かせる
    - serious  : 断定調（末尾を句点で締める）
    - neutral  : 変更なし
    ※ モデルのプロソディを直接制御しないため下位互換で安全。
    """
    s = text.strip()
    st = (style or "neutral").lower()

    if st == "energetic":
        if lang == "ja":
            s = s.rstrip("。!！？」").rstrip()
            s = s + "！"
        else:
            s = s.rstrip(".!? ").rstrip()
            s = s + "!"
    elif st == "calm":
        if lang == "ja":
            s = s.rstrip("。!！？」").rstrip()
            s = s + "。"
        else:
            s = s.rstrip(".!? ").rstrip()
            s = s + "."
    elif st == "serious":
        if lang == "ja":
            s = re.sub(r"[！!？?]+$", "", s).rstrip()
            if not s.endswith("。"):
                s += "。"
        else:
            s = re.sub(r"[!?\s]+$", "", s).rstrip()
            if not s.endswith("."):
                s += "."
    # neutral は変更なし
    return s


def speak(lang: str, speaker: str, text: str, out_path: Path, style: str = "neutral"):
    """
    lang     : 'en', 'ja', 'pt', 'id' など
    speaker  : 'Alice' / 'Bob' / 'N'（N=ナレーションは Alice 側の声を使用）
    text     : セリフ本文
    out_path : 出力先 .mp3 パス
    style    : 'neutral' | 'energetic' | 'calm' | 'serious'
    """
    # 1) テキスト整形 → スタイル適用
    clean_text  = _clean_for_tts(text, lang)
    styled_text = _apply_style(clean_text, lang, style)

    # 2) ボイス選択（N は Alice 側に割当）
    v_a, v_b = VOICE_MAP.get(lang, FALLBACK_VOICES)
    spk = (speaker or "").lower()
    voice_id = v_a if spk in ("alice", "n") else v_b
    # ※ Bob 側に N を合わせたい場合は下のように切替
    # voice_id = v_b if spk in ("bob", "n") else v_a

    # 3) 音声合成（format → response_format に変更）
    resp = client.audio.speech.create(
        model="tts-1",      # より高音質は "tts-1-hd"（コスト↑）
        voice=voice_id,
        input=styled_text,
        response_format="mp3",  # ✅ 最新SDK仕様
    )
    out_path.write_bytes(resp.content)