#!/usr/bin/env python
"""
main.py – VOCAB専用版（単純結合＋日本語ふりがな[TTSのみ]＋先頭無音＋最短1秒）
- 例文は常に「1文だけ」。バリデーション失敗時は最大3回まで再生成し、最後はフェールセーフ。
- 翻訳（字幕）は1行化し、複文は先頭1文のみ採用。URL/絵文字/余分な空白を除去。
- 追加: TARGET_ACCOUNT/--account で combos をアカウント単位に絞り込み可能。
- 追加: topic_picker の文脈ヒント（context）を例文生成に渡して日本語崩れを抑制。
- 追加: ラングエージルール（厳密モノリンガル・記号/注釈禁止）を例文生成に統合。
- 追加: 単語2行の字幕は「例文＋テーマ＋品詞ヒント」で1語に確定する文脈訳へ切替。
"""

import argparse, logging, re, json, subprocess, os, sys  # ← sys を追加
from datetime import datetime
from pathlib import Path
from shutil import rmtree

import yaml
from pydub import AudioSegment
from openai import OpenAI

from config         import BASE, OUTPUT, TEMP
from translate      import translate
from tts_openai     import speak
from audio_fx       import enhance
from bg_image       import fetch as fetch_bg
from thumbnail      import make_thumbnail
from upload_youtube import upload
from topic_picker   import pick_by_content_type

# ───────────────────────────────────────────────
GPT = OpenAI()
CONTENT_MODE = "vocab"
DEBUG_SCRIPT = os.getenv("DEBUG_SCRIPT", "0") == "1"
GAP_MS       = int(os.getenv("GAP_MS", "120"))
PRE_SIL_MS   = int(os.getenv("PRE_SIL_MS", "120"))
MIN_UTTER_MS = int(os.getenv("MIN_UTTER_MS", "1000"))

# ★ 日本語だけ個別に調整できるENV（未設定なら通常値を継承）
GAP_MS_JA       = int(os.getenv("GAP_MS_JA", str(GAP_MS)))
PRE_SIL_MS_JA   = int(os.getenv("PRE_SIL_MS_JA", str(PRE_SIL_MS)))
MIN_UTTER_MS_JA = int(os.getenv("MIN_UTTER_MS_JA", "800"))  # デフォ軽め短縮

# 生成時の温度（必要なら環境変数で上書き）
EX_TEMP_DEFAULT = float(os.getenv("EX_TEMP", "0.35"))   # 例文
LIST_TEMP       = float(os.getenv("LIST_TEMP", "0.30")) # 語彙リスト

LANG_NAME = {
    "en": "English", "pt": "Portuguese", "id": "Indonesian",
    "ja": "Japanese","ko": "Korean", "es": "Spanish",
}

JP_CONV_LABEL = {
    "en": "英会話", "ja": "日本語会話", "es": "スペイン語会話",
    "pt": "ポルトガル語会話", "ko": "韓国語会話", "id": "インドネシア語会話",
}

with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

def reset_temp():
    if TEMP.exists():
        rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

def sanitize_title(raw: str) -> str:
    title = re.sub(r"^\s*(?:\d+\s*[.)]|[-•・])\s*", "", raw)
    title = re.sub(r"[\s\u3000]+", " ", title).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Video"

def _infer_title_lang(audio_lang: str, subs: list[str], combo: dict) -> str:
    if "title_lang" in combo and combo["title_lang"]:
        return combo["title_lang"]
    if len(subs) >= 2:
        return subs[1]
    for s in subs:
        if s != audio_lang:
            return s
    return audio_lang

def resolve_topic(arg_topic: str) -> str:
    # 手入力の topic はそのまま通す（AUTO時の処理は run_all 内で実施）
    return arg_topic

# ───────────────────────────────────────────────
# クリーニング・バリデーション共通
# ───────────────────────────────────────────────
_URL_RE   = re.compile(r"https?://\S+")
_NUM_LEAD = re.compile(r"^\s*\d+[\).:\-]\s*")
_QUOTES   = re.compile(r'^[\"“”\']+|[\"“”\']+$')
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]")  # ざっくり絵文字
_SENT_END = re.compile(r"[。.!?！？]")

def _normalize_spaces(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()

def _clean_strict(text: str) -> str:
    t = (text or "").strip()
    t = _URL_RE.sub("", t)
    t = _NUM_LEAD.sub("", t)
    t = _QUOTES.sub("", t)
    t = _EMOJI_RE.sub("", t)
    # 末尾の余計な記号
    t = re.sub(r"[\:\-–—]\s*$", "", t)
    return _normalize_spaces(t)

def _is_single_sentence(text: str) -> bool:
    return len(_SENT_END.findall(text or "")) <= 1

def _fits_length(text: str, lang_code: str) -> bool:
    if lang_code in ("ja", "ko", "zh"):
        return len(text or "") <= 30
    # 英語などは語数で
    return len(re.findall(r"\b\w+\b", text or "")) <= 12

def _ensure_period_for_sentence(txt: str, lang_code: str) -> str:
    t = txt or ""
    return t if re.search(r"[。.!?！？]$", t) else t + ("。" if lang_code == "ja" else ".")

# 字幕用クリーン（翻訳結果に適用）
def _clean_sub_line(text: str, lang_code: str) -> str:
    t = _clean_strict(text).replace("\n", " ").strip()
    # 複文は「最初の終止まで」を採用
    m = _SENT_END.search(t)
    if m:
        end = m.end()
        t = t[:end]
    return t

# ───────────────────────────────────────────────
# 翻訳の強化（例文用）：translate()が原文のまま返す場合の再実行
# ───────────────────────────────────────────────
_ASCII_ONLY = re.compile(r'^[\x00-\x7F]+$')

def _looks_like_english(s: str) -> bool:
    s = (s or "").strip()
    return bool(_ASCII_ONLY.fullmatch(s)) and bool(re.search(r'[A-Za-z]', s))

def _needs_retranslate(output: str, src_lang: str, target_lang: str, original: str) -> bool:
    if target_lang == src_lang:
        return False
    out = (output or "").strip()
    if not out:
        return True
    if out.lower() == (original or "").strip().lower():
        return True
    if target_lang == "en" and not _looks_like_english(out):
        return True
    return False

def translate_sentence_strict(sentence: str, src_lang: str, target_lang: str) -> str:
    """まず既存 translate を使い、必要なら厳密プロンプトで再翻訳する。"""
    try:
        first = translate(sentence, target_lang)
    except Exception:
        first = ""

    if not _needs_retranslate(first, src_lang, target_lang, sentence):
        return _clean_sub_line(first, target_lang)

    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role":"user",
                "content":(
                    f"Translate from {LANG_NAME.get(src_lang,'source language')} "
                    f"to {LANG_NAME.get(target_lang,'target language')}.\n"
                    "Return ONLY the translation as a single sentence. "
                    "No explanations, no quotes, no extra symbols.\n\n"
                    f"Text: {sentence}"
                )
            }],
            temperature=0.0, top_p=1.0
        )
        out = (rsp.choices[0].message.content or "").strip()
        out = _clean_sub_line(out, target_lang)
        if out:
            return out
    except Exception:
        pass

    # フェイルセーフ：最悪は原文を返す（その後 _clean_sub_line が効く）
    return _clean_sub_line(sentence, target_lang)

# ───────────────────────────────────────────────
# ラングエージルール（厳密モノリンガル & 記号/注釈禁止）
# ───────────────────────────────────────────────
def _lang_rules(lang_code: str) -> str:
    if lang_code == "ja":
        return (
            "Write entirely in Japanese. "
            "Do not include Latin letters or other languages. "
            "Avoid ASCII symbols such as '/', '-', '→', '()', '[]', '<>', and '|'. "
            "No translation glosses, brackets, or country/language mentions."
        )
    lang_name = LANG_NAME.get(lang_code, "English")
    return (
            f"Write entirely in {lang_name}. "
            "Do not code-switch or include other writing systems. "
            "Avoid ASCII symbols like '/', '-', '→', '()', '[]', '<>', and '|'. "
            "No translation glosses, brackets, or country/language mentions."
    )

# ───────────────────────────────────────────────
# 日本語向けヒューリスティック（fallback 用）
# ───────────────────────────────────────────────
def _guess_ja_pos(word: str) -> str:
    """
    ざっくり品詞推定（辞書なし軽量）
    戻り値: "verb" / "iadj" / "naadj" / "noun"
    """
    w = (word or "").strip()
    if not w:
        return "noun"
    if w.endswith(("する", "します", "したい", "した", "しない", "しよう")):
        return "verb"
    if re.search(r"(う|く|ぐ|す|つ|ぬ|む|ぶ|る)$", w):
        return "verb"
    if w.endswith("い"):
        return "iadj"
    if w.endswith(("的", "的な", "風")):
        return "naadj"
    if re.fullmatch(r"[ァ-ヶー]+", w):
        return "noun"
    return "noun"

def _ja_template_fallback(word: str) -> str:
    kind = _guess_ja_pos(word)
    if kind == "verb":
        return f"{word}ところです。"
    if kind == "iadj":
        return f"{word}ですね。"
    if kind == "naadj":
        return f"{word}だね。"
    return f"{word}が必要です。"

# ───────────────────────────────────────────────
# 語彙ユーティリティ
# ───────────────────────────────────────────────
def _example_temp_for(lang_code: str) -> float:
    # 日本語は特に崩れやすいのでさらに低温度
    return 0.20 if lang_code == "ja" else EX_TEMP_DEFAULT

def _gen_example_sentence(word: str, lang_code: str, context_hint: str = "") -> str:
    """
    1文だけ生成。バリデーション不合格なら最大3回まで再生成。
    失敗時フェールセーフ（ja: テンプレ / 他言語: Let's practice ...）
    context_hint を文脈ヒントとして活用。
    """
    lang_name = LANG_NAME.get(lang_code, "English")
    ctx = (context_hint or "").strip()

    rules = _lang_rules(lang_code)

    system = {
        "role": "system",
        "content": (
            "You write exactly ONE natural sentence. "
            "No lists, no quotes, no emojis, no URLs. Keep it monolingual."
        ),
    }

    if lang_code == "ja":
        user = (
            f"{rules} "
            f"単語「{word}」を必ず含めて、日本語で自然な一文をちょうど1つだけ書いてください。"
            "日常の簡単な状況を想定し、助詞の使い方を自然にしてください。"
            "かっこ書きや翻訳注釈は不要です。"
        )
        if ctx:
            user += f" シーンの文脈: {ctx}"
    else:
        user = (
            f"{rules} "
            f"Write exactly ONE short, natural sentence in {lang_name} that uses the word: {word}. "
            "Return ONLY the sentence."
        )
        if ctx:
            user += f" Scene hint: {ctx}"

    for _ in range(3):
        try:
            rsp = GPT.chat.completions.create(
                model="gpt-4o-mini",
                messages=[system, {"role":"user","content":user}],
                temperature=_example_temp_for(lang_code),
                top_p=0.9,
                presence_penalty=0,
                frequency_penalty=0,
            )
            raw = (rsp.choices[0].message.content or "").strip()
        except Exception:
            raw = ""

        cand = _clean_strict(raw)
        valid = bool(cand) and _is_single_sentence(cand) and _fits_length(cand, lang_code)
        try:
            contains_word = (word.lower() in cand.lower()) if lang_code not in ("ja","ko","zh") else (word in cand)
        except Exception:
            contains_word = True

        if valid and contains_word:
            return _ensure_period_for_sentence(cand, lang_code)

    # フェールセーフ
    if lang_code == "ja":
        return _ja_template_fallback(word)
    return _ensure_period_for_sentence(f"Let's practice {word}", lang_code)

def _gen_vocab_list(theme: str, lang_code: str, n: int) -> list[str]:
    theme_for_prompt = translate(theme, lang_code) if lang_code != "en" else theme
    prompt = (
        f"List {n} essential single or hyphenated words for {theme_for_prompt} context "
        f"in {LANG_NAME.get(lang_code,'English')}. Return ONLY one word per line, no numbering."
    )
    content = ""
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=LIST_TEMP,
            top_p=0.9,
            presence_penalty=0,
            frequency_penalty=0,
        )
        content = (rsp.choices[0].message.content or "")
    except Exception:
        content = ""

    words = []
    for line in content.splitlines():
        w = (line or "").strip()
        if not w:
            continue
        w = re.sub(r"^\d+[\).]?\s*", "", w)     # 番号
        w = re.sub(r"[，、。.!?！？]+$", "", w)  # 末尾句読点
        w = w.split()[0]                        # 先頭トークン
        if w and w not in words:
            words.append(w)

    if len(words) >= n:
        return words[:n]
    fallback = ["check-in", "reservation", "checkout", "receipt", "elevator", "lobby", "upgrade"]
    return fallback[:n]

# ───────────────────────────────────────────────
# ★ 追加：spec 正規化＋spec対応の語彙生成（下位互換保持）
# ───────────────────────────────────────────────
def _normalize_spec(picked, context_hint, audio_lang, words_env_count: int):
    """
    topic_picker からの戻り値を正規化:
      - dict(spec) をそのまま受け入れ、欠損は補完
      - (theme, ctx) なら spec を薄く合成
      - str(theme) なら既存互換の最小 spec を生成
    返り値: (theme, context, spec)
    """
    if isinstance(picked, dict):
        theme = picked.get("theme") or "general vocabulary"
        ctx   = picked.get("context") or (context_hint or "")
        spec  = dict(picked)  # コピー
        if "count" not in spec or not isinstance(spec["count"], int):
            spec["count"] = words_env_count
        return theme, ctx, spec

    if isinstance(picked, tuple) and len(picked) == 2:
        theme, ctx = picked[0], picked[1]
        spec = {
            "theme": theme,
            "context": ctx or (context_hint or ""),
            "count": words_env_count,
        }
        return theme, ctx, spec

    # string / その他
    theme = str(picked)
    ctx   = context_hint or ""
    spec = {
        "theme": theme,
        "context": ctx,
        "count": words_env_count,
    }
    return theme, ctx, spec

def _gen_vocab_list_from_spec(spec: dict, lang_code: str) -> list[str]:
    """
    spec に含まれる基準（pos / relation_mode / difficulty / pattern_hint / morphology / count など）を
    プロンプトに反映。未指定は従来挙動。
    """
    n   = int(spec.get("count", int(os.getenv("VOCAB_WORDS", "6"))))
    th  = spec.get("theme") or "general vocabulary"
    pos = spec.get("pos") or []  # ["noun","verb",...]
    rel = (spec.get("relation_mode") or "").strip().lower()  # synonym/antonym/collocation/pattern
    diff = (spec.get("difficulty") or "").strip().upper()    # A1/A2/B1...
    patt = (spec.get("pattern_hint") or "").strip()
    morph = spec.get("morphology") or []                     # ["prefix:un-","suffix:-able"]

    theme_for_prompt = translate(th, lang_code) if lang_code != "en" else th

    lines = []
    lines.append(f"You are selecting {n} HIGH-FREQUENCY words for the topic: {theme_for_prompt}.")
    if pos:
        lines.append("Restrict part-of-speech to: " + ", ".join(pos) + ".")
    if rel == "synonym":
        lines.append("Prefer synonyms or near-synonyms around the central topic.")
    elif rel == "antonym":
        lines.append("Include at least one meaningful antonym pair if possible.")
    elif rel == "collocation":
        lines.append("Prefer common collocations used with the topic in everyday speech.")
    elif rel == "pattern":
        lines.append("Prefer short reusable patterns or set phrases.")
    if patt:
        lines.append(f"Pattern focus hint: {patt}.")
    if morph:
        lines.append("If natural, include related morphological family: " + ", ".join(morph) + ".")
    if diff in ("A1","A2","B1"):
        lines.append(f"Target approximate CEFR level: {diff}. Keep words short and common for this level.")
    lines.append("Return ONLY one word or short hyphenated term per line, no numbering, no punctuation.")
    prompt = "\n".join(lines)

    content = ""
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=LIST_TEMP,
            top_p=0.9,
            presence_penalty=0,
            frequency_penalty=0,
        )
        content = (rsp.choices[0].message.content or "")
    except Exception:
        content = ""

    words = []
    for line in content.splitlines():
        w = (line or "").strip()
        if not w:
            continue
        w = re.sub(r"^\d+[\).]?\s*", "", w)     # 番号除去
        w = re.sub(r"[，、。.!?！？]+$", "", w)  # 末尾句読点除去
        w = w.split()[0]                        # 先頭トークン化
        if w and w not in words:
            words.append(w)

    if len(words) >= n:
        return words[:n]

    # 不足時は従来 fallback
    fallback = ["check-in", "reservation", "checkout", "receipt", "elevator", "lobby", "upgrade"]
    return (words + [w for w in fallback if w not in words])[:n]

# ───────────────────────────────────────────────
# 日本語TTS用ふりがな
# ───────────────────────────────────────────────
_KANJI_ONLY = re.compile(r"^[一-龥々]+$")
_PARENS_JA  = re.compile(r"\s*[\(\（][^)\）]{1,40}[\)\）]\s*")

def _kana_reading(word: str) -> str:
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role":"user",
                "content":(
                    "次の日本語単語の読みをひらがなだけで1語返してください。"
                    "記号・括弧・説明は不要。\n"
                    f"単語: {word}"
                )
            }],
            temperature=0.0,
            top_p=1.0,
        )
        yomi = (rsp.choices[0].message.content or "").strip()
        yomi = re.sub(r"[^ぁ-ゖゝゞー]+", "", yomi)
        return yomi[:20]
    except Exception:
        return ""

# ───────────────────────────────────────────────
# 例文取得（同じ3行ブロックの3行目）
# ───────────────────────────────────────────────
def _example_for_index(valid_dialogue: list[tuple[str, str]], idx0: int) -> str:
    """
    valid_dialogue は 3行1組（[word, word, example]）で並ぶ。
    idx0 がその組の 0/1/2 のいずれでも、例文は常に +2 の位置。
    """
    role_idx = idx0 % 3  # 0/1/2
    base = idx0 - role_idx
    ex_pos = base + 2
    if 0 <= ex_pos < len(valid_dialogue):
        return valid_dialogue[ex_pos][1]
    return ""

# ───────────────────────────────────────────────
# 単語専用・文脈つき翻訳（1語だけ返す）
# ───────────────────────────────────────────────
def translate_word_context(word: str, target_lang: str, src_lang: str, theme: str, example: str, pos_hint: str | None = None) -> str:
    """
    単語の意味を 例文＋テーマ＋品詞ヒント で確定し、target_lang の“1語のみ”を返す。
    """
    theme = (theme or "").strip()
    example = (example or "").strip()
    pos_line = f"Part of speech hint: {pos_hint}." if pos_hint else ""

    prompt_lines = [
        "You are a precise bilingual lexicon generator.",
        f"Source language code: {src_lang}",
        f"Target language code: {target_lang}",
        "Task: Translate the SINGLE WORD below into exactly ONE natural target-language word that matches the intended meaning in the given context.",
        "Rules:",
        "- Output ONLY one word, no punctuation, no quotes, no explanations.",
        "- Choose the sense that fits the context (theme and example sentence).",
        "- Avoid month-name or book-title senses unless clearly indicated by context.",
        pos_line,
        "",
        f"Word: {word}",
        f"Theme: {theme}" if theme else "Theme: (none)",
        f"Example sentence for context: {example}" if example else "Example sentence for context: (none)",
    ]
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":"\n".join(prompt_lines)}],
            temperature=0.0, top_p=1.0
        )
        out = (rsp.choices[0].message.content or "").strip()
        out = re.sub(r"[，、。.!?！？]+$", "", out).strip()
        out = out.split()[0] if out else ""
        return out or word
    except Exception:
        return word

# ───────────────────────────────────────────────
# メタ生成（タイトル言語に統一）
# ───────────────────────────────────────────────
def make_title(theme, title_lang: str, audio_lang_for_label: str | None = None):
    if title_lang not in LANG_NAME:
        title_lang = "en"
    try:
        theme_local = theme if title_lang == "en" else translate(theme, title_lang)
    except Exception:
        theme_local = theme

    if title_lang == "ja":
        base = f"{theme_local} で使える一言"
        label = JP_CONV_LABEL.get(audio_lang_for_label or "", "")
        t = f"{label} {base}" if label and label not in base else base
        return sanitize_title(t)[:28]
    else:
        if title_lang == "en":
            t = f"{theme_local.capitalize()} vocab in one minute"
        else:
            t = f"{theme_local} vocabulary"
        return sanitize_title(t)[:55]

def make_desc(theme, title_lang: str):
    if title_lang not in LANG_NAME:
        title_lang = "en"
    try:
        theme_local = theme if title_lang == "en" else translate(theme, title_lang)
    except Exception:
        theme_local = theme

    msg = {
        "ja": f"{theme_local} に必須の語彙を短時間でチェック。声に出して一緒に練習しよう！ #vocab #learning",
        "en": f"Quick practice for {theme_local} vocabulary. Repeat after the audio! #vocab #learning",
        "pt": f"Pratique rápido o vocabulário de {theme_local}. Repita em voz alta! #vocab #aprendizado",
        "es": f"Práctica rápida de vocabulario de {theme_local}. ¡Repite en voz alta! #vocab #aprendizaje",
        "ko": f"{theme_local} 어휘를 빠르게 연습하세요. 소리 내어 따라 말해요! #vocab #learning",
        "id": f"Latihan cepat kosakata {theme_local}. Ucapkan keras-keras! #vocab #belajar",
    }
    return msg.get(title_lang, msg["en"])

def make_tags(theme, audio_lang, subs, title_lang):
    tags = [
        theme, "vocabulary", "language learning", "speaking practice",
        "listening practice", "subtitles"
    ]
    for code in subs:
        if code in LANG_NAME:
            tags.append(f"{LANG_NAME[code]} subtitles")
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); out.append(t)
    return out[:15]

# ───────────────────────────────────────────────
# 単純結合（WAV中間・行頭無音・最短尺・行間ギャップ）
# ───────────────────────────────────────────────
def _concat_with_gaps(audio_paths, gap_ms=120, pre_ms=120, min_ms=1000):
    combined = AudioSegment.silent(duration=0)
    durs = []
    for idx, p in enumerate(audio_paths):
        seg = AudioSegment.from_file(p)
        seg = AudioSegment.silent(duration=pre_ms) + seg
        if len(seg) < min_ms:
            seg += AudioSegment.silent(duration=min_ms - len(seg))
        seg_ms = len(seg)
        extra = gap_ms if idx < len(audio_paths) - 1 else 0
        combined += seg
        if extra:
            combined += AudioSegment.silent(duration=extra)
        durs.append((seg_ms + extra) / 1000.0)
    (TEMP / "full_raw.wav").unlink(missing_ok=True)
    combined.export(TEMP / "full_raw.wav", format="wav")
    return durs

# ───────────────────────────────────────────────
# 1コンボ処理
# ───────────────────────────────────────────────
def run_one(topic, turns, audio_lang, subs, title_lang, yt_privacy, account, do_upload, chunk_size, context_hint="", spec=None):
    reset_temp()

    raw = (topic or "").replace("\r", "\n").strip()
    is_word_list = bool(re.search(r"[,;\n]", raw)) and len([w for w in re.split(r"[\n,;]+", raw) if w.strip()]) >= 2

    words_count = int(os.getenv("VOCAB_WORDS", "6"))
    if is_word_list:
        vocab_words = [w.strip() for w in re.split(r"[\n,;]+", raw) if w.strip()]
        theme = "custom list"
        local_context = ""  # 手入力リスト時は文脈ヒントなし
    else:
        # spec が来ていればそれを使用
        if isinstance(spec, dict):
            theme = spec.get("theme") or topic
            local_context = (spec.get("context") or context_hint or "")
            vocab_words = _gen_vocab_list_from_spec(spec, audio_lang)
            # デバッグ: spec を保存（常にOK）
            try:
                (TEMP / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        else:
            theme = topic
            vocab_words = _gen_vocab_list(theme, audio_lang, words_count)
            local_context = context_hint or ""  # AUTO時に受け取った文脈を使う

    # 3行ブロック: 単語 → 単語 → 例文
    dialogue = []
    for w in vocab_words:
        ex = _gen_example_sentence(w, audio_lang, local_context)
        dialogue.extend([("N", w), ("N", w), ("N", ex)])

    valid_dialogue = [(spk, line) for (spk, line) in dialogue if line.strip()]
    audio_parts, sub_rows = [], [[] for _ in subs]

    plain_lines = [line for (_, line) in valid_dialogue]
    tts_lines   = []

    for i, (spk, line) in enumerate(valid_dialogue, 1):
        role_idx = (i - 1) % 3  # 0/1/2

        tts_line = line
        if audio_lang == "ja":
            if role_idx == 2:
                # 例文：括弧は読まない + 必ず終止
                tts_line = _PARENS_JA.sub(" ", tts_line).strip()
                tts_line = _ensure_period_for_sentence(tts_line, audio_lang)
            else:
                # 単語行：かな読み＋句点で抑揚安定（ただし1文字語は句点を付けない）
                if _KANJI_ONLY.fullmatch(line):
                    yomi = _kana_reading(line)
                    if yomi:
                        tts_line = yomi
                base = re.sub(r"[。！？!?]+$", "", tts_line).strip()
                tts_line = base + "。" if len(base) >= 2 else base
        else:
            # 非日本語は例文のみ終止を保証
            if role_idx == 2:
                tts_line = _ensure_period_for_sentence(tts_line, audio_lang)

        out_audio = TEMP / f"{i:02d}.wav"
        # 日本語は語尾安定のため serious
        style_for_tts = "serious" if audio_lang == "ja" else "neutral"

        speak(audio_lang, spk, tts_line, out_audio, style=style_for_tts)
        audio_parts.append(out_audio)
        tts_lines.append(tts_line)

        # 字幕（音声言語=原文、他言語=翻訳）→ クリーニングして1行化
        for r, lang in enumerate(subs):
            if lang == audio_lang:
                sub_rows[r].append(_clean_sub_line(line, lang))
            else:
                try:
                    if role_idx in (0, 1):  # 単語2行は文脈つき1語訳
                        example_ctx = _example_for_index(valid_dialogue, i-1)
                        # POSヒント：spec優先→日本語のみ簡易推定
                        pos_hint = None
                        if isinstance(spec, dict) and spec.get("pos"):
                            pos_hint = ",".join(spec["pos"])
                        elif audio_lang == "ja":
                            _k = _guess_ja_pos(line)
                            pos_map = {"verb":"verb", "iadj":"adjective", "naadj":"adjective", "noun":"noun"}
                            pos_hint = pos_map.get(_k, None)

                        trans = translate_word_context(
                            word=line, target_lang=lang, src_lang=audio_lang,
                            theme=theme, example=example_ctx, pos_hint=pos_hint
                        )
                    else:
                        # 例文行はまず通常翻訳 → ダメなら厳密プロンプトで再翻訳
                        trans = translate_sentence_strict(line, src_lang=audio_lang, target_lang=lang)
                except Exception:
                    trans = line
                sub_rows[r].append(_clean_sub_line(trans, lang))

    # 単純結合 → 整音 → mp3
    # ★ 日本語だけ間と最短尺を別ENVで調整
    gap_ms = GAP_MS_JA if audio_lang == "ja" else GAP_MS
    pre_ms = PRE_SIL_MS_JA if audio_lang == "ja" else PRE_SIL_MS
    min_ms = MIN_UTTER_MS_JA if audio_lang == "ja" else MIN_UTTER_MS

    new_durs = _concat_with_gaps(audio_parts, gap_ms=gap_ms, pre_ms=pre_ms, min_ms=min_ms)
    enhance(TEMP/"full_raw.wav", TEMP/"full.wav")
    AudioSegment.from_file(TEMP/"full.wav").export(TEMP/"full.mp3", format="mp3")

    # 背景画像（日本語テーマを英語に翻訳して検索）
    bg_png = TEMP / "bg.png"

    try:
        theme_en = translate(theme, "en")  # 日本語テーマを英語化
    except Exception:
        theme_en = theme

    first_word = valid_dialogue[0][1] if valid_dialogue else theme

    def _is_ascii(s: str) -> bool:
        try:
            s.encode("ascii")
            return True
        except Exception:
            return False

    # 検索クエリ
    if not _is_ascii(first_word or ""):
        query_for_bg = theme_en or "language learning"
    else:
        query_for_bg = first_word or theme_en or "learning"

    fetch_bg(query_for_bg, bg_png)
    
    # lines.json
    lines_data = []
    for i, ((spk, txt), dur) in enumerate(zip(valid_dialogue, new_durs)):
        row = [spk]
        for r in range(len(subs)):
            row.append(sub_rows[r][i])
        row.append(dur)
        lines_data.append(row)
    (TEMP/"lines.json").write_text(json.dumps(lines_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ─────────────────────────
    # デバッグ出力（常に出力する）
    # ─────────────────────────
    try:
        (TEMP / "script_raw.txt").write_text("\n".join(plain_lines), encoding="utf-8")
        (TEMP / "script_tts.txt").write_text("\n".join(tts_lines), encoding="utf-8")
        with open(TEMP / "subs_table.tsv", "w", encoding="utf-8") as f:
            header = ["idx", "text"] + [f"sub:{code}" for code in subs]
            f.write("\t".join(header) + "\n")
            for idx in range(len(valid_dialogue)):
                row = [str(idx+1), _clean_sub_line(valid_dialogue[idx][1], audio_lang)]
                for r in range(len(subs)):
                    row.append(sub_rows[r][idx])
                f.write("\t".join(row) + "\n")
        with open(TEMP / "durations.txt", "w", encoding="utf-8") as f:
            total = 0.0
            for i, d in enumerate(new_durs, 1):
                total += d
                f.write(f"{i:02d}\t{d:.3f}s\n")
            f.write(f"TOTAL\t{total:.3f}s\n")
    except Exception as e:
        logging.warning(f"[DEBUG_SCRIPT] write failed: {e}")

    if args.lines_only:
        return

    # サムネ
    thumb = TEMP / "thumbnail.jpg"
    thumb_lang = subs[1] if len(subs) > 1 else audio_lang
    make_thumbnail(theme, thumb_lang, thumb)

    # 動画生成
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_mp4 = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    final_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python", str(BASE/"chunk_builder.py"),
        str(TEMP/"lines.json"), str(TEMP/"full.mp3"), str(bg_png),
        "--chunk", str(chunk_size),
        "--rows", str(len(subs)),
        "--out", str(final_mp4),
    ]
    logging.info("🔹 chunk_builder cmd: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

    if not do_upload:
        return

    # メタ生成＆アップロード
    title = make_title(theme, title_lang, audio_lang_for_label=audio_lang)
    desc  = make_desc(theme, title_lang)
    tags  = make_tags(theme, audio_lang, subs, title_lang)

    # ─────────────────────────────
    # 改良版アップロード（トークン切れ＆上限対応）
    # ─────────────────────────────
    def _is_limit_error(err: Exception) -> bool:
        s = str(err)
        return (
            "uploadLimitExceeded" in s or
            "quotaExceeded" in s or
            "The user has exceeded the number of videos they may upload" in s
        )

    def _is_token_error(err: Exception) -> bool:
        s = str(err).lower()
        return (
            ("token" in s and "expired" in s) or
            ("invalid_grant" in s) or
            ("unauthorized_client" in s) or
            ("invalid_credentials" in s) or
            ("401" in s)
        )

    def _try_upload_with_fallbacks() -> bool:
        fb = os.getenv("UPLOAD_FALLBACKS", "").strip()
        fallbacks = [x.strip() for x in fb.split(",") if x.strip()]
        tried = []

        for acc in [account] + [a for a in fallbacks if a != account]:
            tried.append(acc)
            try:
                upload(
                    video_path=final_mp4, title=title, desc=desc, tags=tags,
                    privacy=yt_privacy, account=acc, thumbnail=thumb, default_lang=audio_lang
                )
                logging.info(f"[UPLOAD] ✅ success on account='{acc}'")
                return True
            except Exception as e:
                # 上限エラーなら次のアカウントへ
                if _is_limit_error(e):
                    logging.warning(f"[UPLOAD] ⚠️ limit reached on account='{acc}' → trying next fallback.")
                    continue

                # トークン切れ（expire/revoke）なら即停止＋通知
                if _is_token_error(e):
                    logging.error(f"[UPLOAD] ❌ TOKEN ERROR on account='{acc}' — expired/revoked/unauthorized.")
                    try:
                        (TEMP / "TOKEN_EXPIRED.txt").write_text(
                            f"Token expired or revoked for account='{acc}'.\nDetail:\n{e}",
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    raise SystemExit(f"[ABORT] Token expired/revoked for account='{acc}'. Please reauthorize.")

                # 想定外のエラーは raise（バグ検出用）
                logging.exception(f"[UPLOAD] unexpected error on account='{acc}'")
                raise

        # すべて上限エラー → スキップして次のコンボへ進行
        msg = f"Upload skipped due to per-account limits. tried={tried}"
        logging.warning("[UPLOAD] " + msg)
        try:
            (TEMP / "UPLOAD_SKIPPED.txt").write_text(msg, encoding="utf-8")
        except Exception:
            pass
        return False

    _try_upload_with_fallbacks()

# ───────────────────────────────────────────────
def run_all(topic, turns, privacy, do_upload, chunk_size):
    """
    親プロセス: 各 account ごとに子プロセスを起動（ISOLATED_RUN=1 を付与）
    子プロセス(ISOLATED_RUN=1): そのまま run_one を実行（再帰起動しない）
    """
    isolated = os.getenv("ISOLATED_RUN", "0") == "1"

    if isolated:
        # ここは子プロセス用：従来通りに実行（TARGET_ONLY があれば 1 アカウントのみになる）
        for combo in COMBOS:
            audio_lang  = combo["audio"]
            subs        = combo["subs"]
            account     = combo.get("account","default")
            title_lang  = _infer_title_lang(audio_lang, subs, combo)

            if TARGET_ONLY and account != TARGET_ONLY:
                continue

            picked_topic = topic
            context_hint = ""
            spec_for_run = None
            words_env_count = int(os.getenv("VOCAB_WORDS", "6"))

            if topic.strip().lower() == "auto":
                try:
                    picked_raw = pick_by_content_type("vocab", audio_lang, return_context=True)
                    picked_topic, context_hint, spec_for_run = _normalize_spec(
                        picked_raw, context_hint, audio_lang, words_env_count
                    )
                except TypeError:
                    picked_raw = pick_by_content_type("vocab", audio_lang)
                    picked_topic, context_hint, spec_for_run = _normalize_spec(
                        picked_raw, context_hint, audio_lang, words_env_count
                    )

            logging.info(f"[ISOLATED] {audio_lang} | subs={subs} | account={account} | theme={picked_topic}")
            run_one(
                picked_topic, turns, audio_lang, subs, title_lang,
                privacy, account, do_upload, chunk_size,
                context_hint=context_hint, spec=spec_for_run
            )
        return

    # ここは親プロセス：各アカウントごとに子プロセスで独立実行
    for combo in COMBOS:
        account = combo.get("account", "default")
        if TARGET_ONLY and account != TARGET_ONLY:
            continue

        cmd = [
            sys.executable, str(BASE / "main.py"),
            topic,
            "--privacy", privacy,
            "--chunk", str(chunk_size),
            "--account", account,
        ]
        if not do_upload:
            cmd.append("--no-upload")

        env = os.environ.copy()
        env["ISOLATED_RUN"] = "1"   # ← 子プロセス側で再帰起動を止めるためのフラグ

        logging.info(f"▶ Spawning isolated run for account={account}: {' '.join(cmd)}")
        subprocess.run(cmd, check=False, env=env)

# ───────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="語彙テーマ。AUTO で自動選択。カンマ/改行区切りなら単語リストとして使用")
    ap.add_argument("--turns", type=int, default=8)  # 互換用
    ap.add_argument("--privacy", default="unlisted", choices=["public","unlisted","private"])
    ap.add_argument("--lines-only", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--chunk", type=int, default=9999, help="Shortsは分割せず1本推奨")
    # ★ 追加: CLIからアカウントを指定できる
    ap.add_argument("--account", type=str, default="", help="この account のみ実行（combos.yaml の account 値に一致）")
    args = ap.parse_args()

    # ── Account フィルタの決定（CLI > 環境変数） ──
    target_cli = (args.account or "").strip()
    target_env = os.getenv("TARGET_ACCOUNT", "").strip()
    TARGET_ONLY = target_cli or target_env

    if TARGET_ONLY:
        selected = [c for c in COMBOS if c.get("account", "default") == TARGET_ONLY]
        if not selected:
            logging.error(f"[ABORT] No combos matched account='{TARGET_ONLY}'. Check combos.yaml.")
            raise SystemExit(2)
        # in-place 置換（他からも参照されるため）
        COMBOS[:] = selected
        logging.info(f"[ACCOUNT FILTER] Running only for account='{TARGET_ONLY}' ({len(COMBOS)} combo(s)).")

    topic = resolve_topic(args.topic)
    run_all(topic, args.turns, args.privacy, not args.no_upload, args.chunk)