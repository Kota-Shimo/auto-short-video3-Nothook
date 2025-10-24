"""OpenAI TTS wrapper – language-aware & two-speaker support with simple style control.
- JAだけ高音質モデル（デフォ: tts-1-hd）
- 句読点の正規化＆軽いポーズ挿入で日本語の聞きやすさ向上
"""

import os
import re
from pathlib import Path
from openai import OpenAI
from config import OPENAI_API_KEY, VOICE_MAP

client = OpenAI(api_key=OPENAI_API_KEY)

# VOICE_MAP に無い言語のフォールバック（Alice, Bob）
FALLBACK_VOICES = ("alloy", "echo")

# 環境変数でモデル/フォーマットを上書き可能
TTS_MODEL_DEFAULT = os.getenv("TTS_MODEL_DEFAULT", "tts-1")
TTS_MODEL_JA      = os.getenv("TTS_MODEL_JA", "tts-1-hd")  # ← 日本語は高音質
TTS_FORMAT        = os.getenv("TTS_FORMAT", "mp3")         # "mp3" / "wav" など


def _clean_for_tts(text: str, lang: str) -> str:
    """
    音声合成前の整形：
    - 冒頭の話者ラベル（Alice:/Bob:/N:）を除去
    - 余分な空白・改行を整理
    - 日本語はローマ字/英単語・一部記号を除去して誤読を抑制
    """
    t = re.sub(r"^[A-Za-z]+:\s*", "", text or "")  # Alice:/Bob:/N: を削除
    t = re.sub(r"\s+", " ", t).strip()

    if lang == "ja":
        t = re.sub(r"[A-Za-z]+", "", t)      # ローマ字/英単語の排除（数字は残す）
        t = re.sub(r"[#\"'※＊*~`]", "", t)   # 記号の整理
        t = re.sub(r"\s+", " ", t).strip()

    return t or ("。" if lang == "ja" else ".")


def _normalize_ja_punct(s: str) -> str:
    """日本語の句読点を全角に寄せる & 末尾終止を保証。"""
    if not s:
        return "。"
    # ASCII 記号→全角
    s = s.replace("...", "…")
    s = s.replace(".", "。").replace(",", "、")
    s = s.replace("!", "！").replace("?", "？")
    s = re.sub(r"\s+", " ", s).strip()
    # 末尾終止
    if not re.search(r"[。！？]$", s):
        s += "。"
    return s


def _auto_pause_ja(s: str) -> str:
    """
    「、」が全く無い長めの文に、軽くポーズを入れる。
    乱挿入は避け、接続詞や助詞の直前で1箇所だけ。
    """
    if "、" in s or len(s) <= 16:
        return s

    # 接続詞や転換語の手前にだけ挿入候補
    CUES = ["けど", "でも", "しかし", "それで", "だから", "そして", "ただ", "ただし", "でもね", "一方で"]
    for cue in CUES:
        idx = s.find(cue)
        if idx > 6:  # 冒頭すぐは避ける
            return s[:idx] + "、" + s[idx:]

    # 上記が無ければ、おおよそ中間で安全な位置に1つ
    pos = min(max(len(s) // 2, 10), len(s) - 5)
    return s[:pos] + "、" + s[pos:]


def _apply_style(text: str, lang: str, style: str) -> str:
    """
    句読点で“抑揚”を軽く誘導する簡易スタイル。
    - energetic: 感嘆系で勢いをつける
    - calm     : 句点で落ち着かせる
    - serious  : 断定調（末尾を句点で締める）
    - neutral  : 変更なし
    """
    s = text.strip()
    st = (style or "neutral").lower()

    if lang == "ja":
        s = _normalize_ja_punct(s)
        s = _auto_pause_ja(s)

        if st == "energetic":
            s = re.sub(r"[。]+$", "！", s)
        elif st in ("calm", "serious"):
            s = re.sub(r"[！？」]+$", "", s)
            if not s.endswith("。"):
                s += "。"
        return s

    # 非JA
    if st == "energetic":
        s = s.rstrip(".!? ").rstrip() + "!"
    elif st in ("calm", "serious"):
        s = re.sub(r"[!?\s]+$", "", s).rstrip()
        if not s.endswith("."):
            s += "."
    return s


def _pick_voice(lang: str, speaker: str) -> str:
    """話者に応じたボイス選択。N は Alice 側に割り当て。"""
    v_a, v_b = VOICE_MAP.get(lang, FALLBACK_VOICES)
    spk = (speaker or "").lower()
    return v_a if spk in ("alice", "n") else v_b
    # ※ Bob 側に N を合わせたい場合は下のように切替
    # return v_b if spk in ("bob", "n") else v_a


def _pick_model(lang: str) -> str:
    """言語別モデル選択（日本語だけ高音質）。"""
    if lang == "ja":
        return TTS_MODEL_JA or TTS_MODEL_DEFAULT
    return TTS_MODEL_DEFAULT


def speak(lang: str, speaker: str, text: str, out_path: Path, style: str = "neutral"):
    """
    lang     : 'en', 'ja', 'pt', 'id' など
    speaker  : 'Alice' / 'Bob' / 'N'（N=ナレーションは Alice 側の声を使用）
    text     : セリフ本文
    out_path : 出力先 .mp3/.wav パス
    style    : 'neutral' | 'energetic' | 'calm' | 'serious'
    """
    # 1) テキスト整形 → スタイル適用
    clean_text  = _clean_for_tts(text, lang)
    styled_text = _apply_style(clean_text, lang, style)

    # 2) モデル/ボイス
    model    = _pick_model(lang)
    voice_id = _pick_voice(lang, speaker)
    fmt      = (out_path.suffix[1:].lower() or TTS_FORMAT) if out_path.suffix else TTS_FORMAT

    # 3) 音声合成
    resp = client.audio.speech.create(
        model=model,         # ja: tts-1-hd / others: tts-1（既定）
        voice=voice_id,
        input=styled_text,
        format=fmt,          # 明示（mp3/wav）
    )
    out_path.write_bytes(resp.content)