#!/usr/bin/env python
"""
main.py – VOCAB専用版（単純結合＋日本語ふりがな[TTSのみ]＋先頭無音＋最短1秒）
- 例文は常に「1文だけ」。バリデーション失敗時は最大5回まで再生成し、最後はフェールセーフ（多言語）。
- 翻訳（字幕）は1行化し、複文は先頭1文のみ採用。URL/絵文字/余分な空白を除去。
- 追加: TARGET_ACCOUNT/--account で combos をアカウント単位に絞り込み可能。
- 追加: topic_picker の文脈ヒント（context）を例文生成に渡して日本語崩れを抑制。
- 追加: ラングエージェルール（厳密モノリンガル・記号/注釈禁止）を例文生成に統合。
- 追加: 単語2行の字幕は「例文＋テーマ＋品詞ヒント」で1語に確定する文脈訳へ切替。
- 追加: 日本語の例文行も“かな読み”に変換して読み上げ可能（字幕は原文のまま）。
- 追加: 語彙バリエーション最適化（直近履歴ペナルティ＋再生成）で「同じ単語ばかり」を回避。
- 追加: テーマ回転（直近テーマの回避）で「同じテーマ連続」を抑制。
"""

import argparse, logging, re, json, subprocess, os, sys, random, time
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
# ★ トレンド取得モジュール（Google News RSS）
from trend_fetcher  import get_trend_candidates
import datetime as dt

from hook import generate_hook

HOOK_ENABLE = os.getenv("HOOK_ENABLE", "1") == "1"
HOOK_STYLE  = os.getenv("HOOK_STYLE", "energetic")

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
MIN_UTTER_MS_JA = int(os.getenv("MIN_UTTER_MS_JA", "800"))

# ★ 例文の“かな読み”トグル
JA_EX_READING = os.getenv("JA_EX_READING", "auto").lower()  # "auto" | "on" | "off"
JA_EX_READING_KANJI_RATIO = float(os.getenv("JA_EX_READING_KANJI_RATIO", "0.25"))
JA_EX_READING_MAX_LEN     = int(os.getenv("JA_EX_READING_MAX_LEN", "60"))

# 生成時の温度（必要なら環境変数で上書き）
EX_TEMP_DEFAULT = float(os.getenv("EX_TEMP", "0.35"))   # 例文
LIST_TEMP       = float(os.getenv("LIST_TEMP", "0.30")) # 語彙リスト

# ── バリエーション設定（ENVで上書き可）
VAR_RECENT_VIDEOS      = int(os.getenv("VAR_RECENT_VIDEOS", "30"))    # 直近何本ぶんを参照（語彙）
VAR_RECENT_DAYS        = int(os.getenv("VAR_RECENT_DAYS", "7"))       # 直近何日ぶんを参照（語彙）
VAR_MAX_OVERLAP_RATIO  = float(os.getenv("VAR_MAX_OVERLAP_RATIO", "0.34"))  # 新語群と直近語彙の重複率上限
VAR_REGEN_ATTEMPTS     = int(os.getenv("VAR_REGEN_ATTEMPTS", "3"))    # 高重複時の再生成回数
VAR_TEMP_BUMP          = float(os.getenv("VAR_TEMP_BUMP", "0.10"))    # 再生成ごとの温度加算
VAR_RECENT_PENALTY     = float(os.getenv("VAR_RECENT_PENALTY", "0.65"))  # 最近語の重み係数（小さいほど当たりにくい）
VAR_HISTORY_FILE       = os.getenv("VAR_HISTORY_FILE", str((OUTPUT / "vocab_history.json").resolve()))

# ── テーマ回転（ENVで上書き可）
THEME_RECENT_VIDEOS   = int(os.getenv("THEME_RECENT_VIDEOS", "30"))  # 直近何本ぶん参照（テーマ）
THEME_RECENT_DAYS     = int(os.getenv("THEME_RECENT_DAYS", "7"))     # 直近何日ぶん参照（テーマ）
THEME_REGEN_ATTEMPTS  = int(os.getenv("THEME_REGEN_ATTEMPTS", "3"))  # AUTO の引き直し最大回数

# 軽いシード分散（被り低減）
random.seed(int(time.time() // 3600) ^ hash((os.getenv("TARGET_ACCOUNT",""), os.getpid())))

LANG_NAME = {
    "en": "English", "pt": "Portuguese", "id": "Indonesian",
    "ja": "Japanese","ko": "Korean", "es": "Spanish", "fr": "French",
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
    return arg_topic

# ───────────────────────────────────────────────
# クリーニング・バリデーション共通
# ───────────────────────────────────────────────
_URL_RE   = re.compile(r"https?://\S+")
_NUM_LEAD = re.compile(r"^\s*\d+[\).:\-]\s*")
_QUOTES   = re.compile(r'^[\"“”\']+|[\"“”\']+$')
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]")
_SENT_END = re.compile(r"[。.!?！？]")

def _normalize_spaces(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()

def _clean_strict(text: str) -> str:
    t = (text or "").strip()
    t = _URL_RE.sub("", t)
    t = _NUM_LEAD.sub("", t)
    t = _QUOTES.sub("", t)
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"[\:\-–—]\s*$", "", t)
    return _normalize_spaces(t)

def _is_single_sentence(text: str) -> bool:
    return len(_SENT_END.findall(text or "")) <= 1

def _fits_length(text: str, lang_code: str) -> bool:
    if lang_code in ("ja", "ko", "zh"):
        return len(text or "") <= 30
    return len(re.findall(r"\b\w+\b", text or "")) <= 12

def _ensure_period_for_sentence(txt: str, lang_code: str) -> str:
    t = txt or ""
    return t if re.search(r"[。.!?！？]$", t) else t + ("。" if lang_code == "ja" else ".")

def _clean_sub_line(text: str, lang_code: str) -> str:
    t = _clean_strict(text).replace("\n", " ").strip()
    m = _SENT_END.search(t)
    if m:
        end = m.end()
        t = t[:end]
    return t

# フック行（2文まで許容）
def _clean_sub_line_hook(text: str, lang_code: str, max_sents: int = 2, max_len: int = 120) -> str:
    t = _clean_strict(text).replace("\n", " ").strip()
    ends = list(_SENT_END.finditer(t))
    if len(ends) >= max_sents:
        t = t[:ends[max_sents-1].end()]
    if len(t) > max_len:
        t = t[:max_len].rstrip(" .、。!！?？") + "…"
    return t

# ───────────────────────────────────────────────
# 英語の機能語（モーダル等）排除 & 内容語抽出
# ───────────────────────────────────────────────
MODAL_STOPWORDS_EN = {
    "would","could","should","may","might","can","must","shall","will",
    "couldn’t","wouldn’t","shouldn’t","’ll","ll","’d","d","’ve","ve","’re","re","’m","m"
}
AUX_STOPWORDS_EN = {"be","am","is","are","was","were","been","being","do","does","did","have","has","had"}
FUNC_STOPWORDS_EN = {
    "please","the","a","an","to","of","for","on","in","at","with","by","and","or","but",
    "this","that","these","those","my","your","his","her","their","our","it","its","i","you","he","she","they","we",
    "me","him","her","them","us"
}
BLOCK_TOKENS_ANY = {"#", "@", "/", "\\", "|"}

def _is_probable_proper_noun_en(token: str) -> bool:
    return len(token) >= 2 and token[0].isupper() and token[1:].islower()

_word_re_en = re.compile(r"[A-Za-z][A-Za-z\-']+")

def pick_content_token(line: str, lang_code: str) -> str:
    """
    1行（LLM出力）から “内容語” を1語だけ取り出す。
    - 英語: モーダル/助動詞/機能語/固有名詞っぽい語を除外。記号・数字も除外。
    - その他言語: #,@,数字混じり等を弾き、最初に残る語を返す（軽フィルタ）。
    """
    if not line:
        return ""
    raw = line.strip()

    if lang_code == "en":
        candidates = _word_re_en.findall(raw)
        for cand in candidates:
            low = cand.lower()
            if any(sym in cand for sym in BLOCK_TOKENS_ANY):
                continue
            if any(ch.isdigit() for ch in cand):
                continue
            if (low in MODAL_STOPWORDS_EN or low in AUX_STOPWORDS_EN or low in FUNC_STOPWORDS_EN):
                continue
            if _is_probable_proper_noun_en(cand):
                continue
            return low  # 英語は小文字に揃える
        return ""

    # 非英語：軽フィルタ
    for tok in raw.split():
        t = tok.strip(".,!?;:()[]{}，、。！？・／／\\|\"'“”‘’")
        if not t:
            continue
        if any(sym in t for sym in BLOCK_TOKENS_ANY):
            continue
        if any(ch.isdigit() for ch in t):
            continue
        return t
    return ""

# ───────────────────────────────────────────────
# 翻訳の強化（例文用）
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

def translate_sentence_strict(
    sentence: str,
    src_lang: str,
    target_lang: str,
    max_sents: int = 1,
    max_len: int = 120
) -> str:
    try:
        first = translate(sentence, target_lang)
    except Exception:
        first = ""

    def _final_clean(s: str) -> str:
        if max_sents == 1:
            return _clean_sub_line(s, target_lang)
        else:
            return _clean_sub_line_hook(s, target_lang, max_sents=max_sents, max_len=max_len)

    if not _needs_retranslate(first, src_lang, target_lang, sentence):
        return _final_clean(first)

    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role":"user",
                "content":(
                    f"Translate from {LANG_NAME.get(src_lang,'source language')} "
                    f"to {LANG_NAME.get(target_lang,'target language')}.\n"
                    "Return ONLY the translation. No explanations, no quotes, no extra symbols.\n\n"
                    f"Text: {sentence}"
                )
            }],
            temperature=0.0, top_p=1.0
        )
        out = (rsp.choices[0].message.content or "").strip()
        return _final_clean(out)
    except Exception:
        return _final_clean(sentence)

# ───────────────────────────────────────────────
# ラングエージルール
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
# 日本語向けヒューリスティック
# ───────────────────────────────────────────────
def _guess_ja_pos(word: str) -> str:
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
    return 0.20 if lang_code == "ja" else EX_TEMP_DEFAULT

def _gen_example_sentence(
    word: str,
    lang_code: str,
    context_hint: str = "",
    difficulty: str | None = None,
) -> str:
    lang_name = LANG_NAME.get(lang_code, "English")
    ctx = (context_hint or "").strip()
    diff = (difficulty or "").strip().upper()
    if diff not in ("A1", "A2", "B1", "B2"):
        diff = ""

    is_trend = "[TREND]" in ctx
    rules = _lang_rules(lang_code)

    cefr_guides = {
        "A1": ("Use very simple, high-frequency words. Present tense. One clause only. No subclauses, no passive, no numbers or dates. Keep it short and concrete."),
        "A2": ("Use common everyday words. Prefer present or simple past. One short clause (or two joined by 'and' at most). Avoid complex relative clauses or conditionals."),
        "B1": ("Use clear, everyday language with slightly more detail. One sentence, but may include a short reason or condition. Avoid rare idioms."),
        "B2": ("Use natural, precise language. One sentence with good flow; mild nuance allowed, but avoid overly technical words."),
        "":  (""),
    }
    cefr_line = cefr_guides.get(diff, "")

    system = {"role":"system","content":"You write exactly ONE natural sentence. No lists, no quotes, no emojis, no URLs. Keep it monolingual."}

    if lang_code == "ja":
        user = (
            f"{rules} 単語「{word}」を**その表記のまま**必ず含めて、日本語で自然な一文をちょうど1つだけ書いてください。"
            "かっこ書きや翻訳注釈は不要です。引用符・スラッシュ等のASCII記号は使わないでください。"
        )
        if ctx: user += f" シーンの文脈: {ctx}"
        if cefr_line:
            user += " 難易度目安: " + {
                "A1": "ごく簡単な語で、現在形。節は1つだけ。",
                "A2": "日常語で短く。現在形中心。複雑な関係節は使わない。",
                "B1": "わかりやすく。理由や条件を短く含めてもよいが1文で。",
                "B2": "自然で正確に。専門的すぎる語は避ける。"
            }[diff]
    else:
        user = (
            f"{rules} Write exactly ONE short, natural sentence in {lang_name} that uses the token **{word}** verbatim."
            " Do not add quotes, brackets, or slashes. Return ONLY the sentence."
        )
        if ctx: user += f" Scene hint: {ctx}"
        if cefr_line: user += f" CEFR level: {diff}. {cefr_line}"

    if   diff == "A1": base_temp = 0.10
    elif diff == "A2": base_temp = 0.18 if lang_code == "ja" else 0.22
    elif diff == "B1": base_temp = 0.28
    elif diff == "B2": base_temp = 0.32
    else:              base_temp = _example_temp_for(lang_code)
    local_temp = max(0.05, base_temp - 0.05) if is_trend else base_temp

    def _fits_len_trendaware(text: str) -> bool:
        if lang_code in ("ja","ko","zh"):
            limit = 34 if is_trend else 30
            return len(text or "") <= limit
        else:
            words = re.findall(r"\b\w+\b", text or "")
            limit = 14 if is_trend else 12
            return len(words) <= limit

    def _contains_token_trendaware(surface: str, sent: str) -> bool:
        try:
            if lang_code in ("ja","ko","zh"):
                if surface in sent:
                    return True
                if lang_code == "ja" and len(surface) >= 2:
                    stem = re.sub(r"[ますでしただたいないよううくぐすつぬむぶるたてでん]?$", "", surface)
                    if stem and stem in sent:
                        return True
                return False
            return surface.lower() in (sent or "").lower()
        except Exception:
            return True

    tries = 7 if is_trend else 5

    for _ in range(tries):
        try:
            rsp = GPT.chat.completions.create(
                model="gpt-4o-mini",
                messages=[system, {"role":"user","content":user}],
                temperature=local_temp, top_p=0.9,
                presence_penalty=0, frequency_penalty=0,
            )
            raw = (rsp.choices[0].message.content or "").strip()
        except Exception:
            raw = ""
        cand = _clean_strict(raw)
        valid = bool(cand) and _is_single_sentence(cand) and _fits_len_trendaware(cand)
        contains_word = _contains_token_trendaware(word, cand)
        if valid and contains_word:
            return _ensure_period_for_sentence(cand, lang_code)

    if lang_code == "ja":
        return _ja_template_fallback(word)
    elif lang_code == "es":
        return _ensure_period_for_sentence(f"Practiquemos {word}", lang_code)
    elif lang_code == "pt":
        return _ensure_period_for_sentence(f"Vamos praticar {word}", lang_code)
    elif lang_code == "fr":
        return _ensure_period_for_sentence(f"Pratiquons {word}", lang_code)
    elif lang_code == "id":
        return _ensure_period_for_sentence(f"Ayo berlatih {word}", lang_code)
    elif lang_code == "ko":
        return _ensure_period_for_sentence(f"{word}를 연습해 봅시다", lang_code)
    else:
        return _ensure_period_for_sentence(f"Let's practice {word}", lang_code)

# ───────────────────────────────────────────────
# バリエーション履歴ユーティリティ（語彙・テーマ共通）
# ───────────────────────────────────────────────
def _load_history():
    try:
        p = Path(VAR_HISTORY_FILE)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"items": []}  # { items: [ {ts, audio_lang, theme, words:[...]} , ...] }

def _save_history(entry):
    data = _load_history()
    data["items"].append(entry)
    if len(data["items"]) > 1000:
        data["items"] = data["items"][-1000:]
    try:
        Path(VAR_HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(VAR_HISTORY_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logging.warning(f"[VARIETY] failed to save history: {e}")

def _recent_words(audio_lang: str):
    """直近 VAR_RECENT_VIDEOS 本・VAR_RECENT_DAYS 日の語だけ抽出"""
    data = _load_history()
    if not data.get("items"):
        return set(), []
    now = time.time()
    day_sec = 86400
    picked = []
    for item in reversed(data["items"]):
        if len(picked) >= VAR_RECENT_VIDEOS:
            break
        if (now - item.get("ts", now)) > VAR_RECENT_DAYS * day_sec:
            continue
        if item.get("audio_lang") != audio_lang:
            continue
        picked.append(item)
    flat = []
    for it in picked:
        flat.extend(it.get("words", []))
    return set(flat), picked

def _diversify_words(candidates: list[str], audio_lang: str, need_n: int) -> list[str]:
    """最近よく出た語を“弱く”しながらランダム選抜（完全除外はしない）"""
    recent_set, _ = _recent_words(audio_lang)
    if not candidates:
        return []
    weighted = []
    for w in candidates:
        base = 1.0
        if w in recent_set:
            base *= VAR_RECENT_PENALTY
        jitter = 0.85 + random.random() * 0.3  # 0.85〜1.15
        weighted.append((w, base * jitter))
    pool = weighted[:]
    out = []
    while pool and len(out) < need_n:
        total = sum(wt for _, wt in pool)
        r = random.random() * (total if total > 0 else 1)
        acc = 0
        for i, (w, wt) in enumerate(pool):
            acc += wt
            if acc >= r:
                out.append(w)
                pool.pop(i)
                break
    if len(out) < need_n:
        remain = [w for (w, _) in pool]
        random.shuffle(remain)
        out += remain[: need_n - len(out)]
    return out[:need_n]

def _overlap_ratio(new_words: list[str], audio_lang: str) -> float:
    recent_set, _ = _recent_words(audio_lang)
    if not new_words:
        return 0.0
    inter = sum(1 for w in new_words if w in recent_set)
    return inter / max(1, len(new_words))

# ───────────────────────────────────────────────
# ★ テーマ回転用ユーティリティ
# ───────────────────────────────────────────────
def _recent_themes(audio_lang: str):
    """直近 THEME_RECENT_VIDEOS 本 & THEME_RECENT_DAYS 日のテーマ集合"""
    data = _load_history()
    if not data.get("items"):
        return set(), []
    now = time.time()
    day_sec = 86400
    picked = []
    for item in reversed(data["items"]):
        if len(picked) >= THEME_RECENT_VIDEOS:
            break
        if (now - item.get("ts", now)) > THEME_RECENT_DAYS * day_sec:
            continue
        if item.get("audio_lang") != audio_lang:
            continue
        picked.append(item)
    themes = [it.get("theme", "") for it in picked if it.get("theme")]
    return set(themes), picked

def _avoid_recent_theme(picked_theme: str, candidates: list[str], audio_lang: str) -> str:
    """
    picked_theme が最近テーマとかぶる場合、候補から最近テーマを避けて差し替え。
    候補が全部かぶるならそのまま返す（過度なループ回避）。
    """
    recent_set, _ = _recent_themes(audio_lang)
    if picked_theme and picked_theme not in recent_set:
        return picked_theme
    if not candidates:
        return picked_theme
    for cand in candidates:
        if cand and cand not in recent_set:
            return cand
    return picked_theme

# ───────────────────────────────────────────────
# 語彙リスト生成（spec対応＋バリエーション層）
# ───────────────────────────────────────────────
def _gen_vocab_list_from_spec(spec: dict, lang_code: str) -> list[str]:
    n   = int(spec.get("count", int(os.getenv("VOCAB_WORDS", "6"))))
    th  = spec.get("theme") or "general vocabulary"
    pos = spec.get("pos") or []
    rel = (spec.get("relation_mode") or "").strip().lower()
    diff = (spec.get("difficulty") or "").strip().upper()
    patt = (spec.get("pattern_hint") or "").strip()
    morph = spec.get("morphology") or []
    is_trend = bool(spec.get("trend"))

    theme_for_prompt = translate(th, lang_code) if lang_code != "en" else th

    lines = []
    lines.append(f"You are selecting {n} HIGH-FREQUENCY **content words** for the topic: {theme_for_prompt}.")
    lines.append("Return EXACTLY one token per line (no numbering, no punctuation).")
    lines.append(f"All words must be written in {LANG_NAME.get(lang_code,'the target')} language.")
    lines.append("Prefer concrete or meaningful nouns, verbs, adjectives, and short reusable set phrases.")
    lines.append("Avoid helper/function words:")
    lines.append("- DO NOT output modal/auxiliary verbs (would, could, may, should, can, must, be, do, have).")
    lines.append("- DO NOT output pronouns, articles, prepositions, determiners (the, a, to, of, on, in, etc).")
    lines.append("- DO NOT output 'please' or similar politeness-only markers.")
    lines.append("Avoid proper nouns (names of people/brands/places), hashtags, usernames, numbers, dates, or URLs.")
    lines.append("If the scene implies politeness (e.g., a restaurant), output **scene content words** instead:")
    lines.append("examples: menu, order, bill, seat, waiter, request, table, dish, reservation.")
    if pos: lines.append("Restrict part-of-speech to: " + ", ".join(pos) + ".")
    if rel == "synonym":
        lines.append("Prefer synonyms or near-synonyms around the central topic.")
    elif rel == "antonym":
        lines.append("Include at least one meaningful antonym pair if natural.")
    elif rel == "collocation":
        lines.append("Prefer common collocations used with the topic in everyday speech.")
    elif rel == "pattern":
        lines.append("Prefer short reusable patterns or set phrases.")
    elif rel == "contextual":
        lines.append("Focus on words useful in natural conversation about this topic: opinions, reasons, actions, feelings, plans, tickets, time, place.")
        lines.append("Avoid rare proper nouns; prefer reusable mid-frequency conversation words.")
    if patt:
        lines.append(f"Pattern focus hint: {patt}.")
    if morph:
        lines.append("If natural, include related morphological family: " + ", ".join(morph) + ".")
    if is_trend:
        lines.append("Do NOT include names of people, teams, brands, hashtags, usernames, or titles of works.")
        lines.append("Avoid multi-word proper nouns and words that require capitalization in general use.")
        lines.append("Prefer single tokens that can be used in everyday sentences about the topic.")
    if diff in ("A1","A2","B1"):
        lines.append(f"Target approximate CEFR level: {diff}. Keep words short and common for this level.")
    lines.append("Output format: one token per line only.")
    prompt = "\n".join(lines)

    content = ""
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=LIST_TEMP, top_p=0.9,
            presence_penalty=0, frequency_penalty=0,
        )
        content = (rsp.choices[0].message.content or "")
    except Exception:
        content = ""

    # LLM出力 → 内容語抽出
    base_words = []
    for line in content.splitlines():
        ln = (line or "").strip()
        if not ln:
            continue
        ln = re.sub(r"^\d+[\).]?\s*", "", ln)
        ln = re.sub(r"[，、。.!?！？]+$", "", ln)

        w = pick_content_token(ln, lang_code)
        if not w:
            continue

        if is_trend:
            if re.search(r"[#@/0-9]", w):
                continue
            if lang_code == "en" and len(w) >= 2 and w[0].isupper() and w[1:].islower():
                continue

        if w not in base_words:
            base_words.append(w)

    # バリエーション層：最近語を弱めて抽出
    diversified = _diversify_words(base_words, lang_code, n)

    # 重複率が高すぎるときは温度を上げて再生成し、再サンプリング
    attempts = 0
    local_list_temp = LIST_TEMP
    while _overlap_ratio(diversified, lang_code) > VAR_MAX_OVERLAP_RATIO and attempts < VAR_REGEN_ATTEMPTS:
        attempts += 1
        try:
            rsp = GPT.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":prompt}],
                temperature=min(0.9, local_list_temp + VAR_TEMP_BUMP),
                top_p=0.9, presence_penalty=0, frequency_penalty=0,
            )
            content2 = (rsp.choices[0].message.content or "")
        except Exception:
            break

        words2 = []
        for line in content2.splitlines():
            ln = (line or "").strip()
            if not ln:
                continue
            ln = re.sub(r"^\d+[\).]?\s*", "", ln)
            ln = re.sub(r"[，、。.!?！？]+$", "", ln)
            w2 = pick_content_token(ln, lang_code)
            if w2 and w2 not in words2:
                words2.append(w2)

        merged = []
        seen = set()
        for w in (base_words + words2):
            if w not in seen:
                merged.append(w); seen.add(w)
        diversified = _diversify_words(merged, lang_code, n)
        local_list_temp += VAR_TEMP_BUMP

    if len(diversified) >= n:
        return diversified[:n]

    # 足りない分はフォールバック少量
    fallback = ["check-in", "reservation", "checkout", "receipt", "elevator", "lobby", "upgrade"]
    return (diversified + [w for w in fallback if w not in diversified])[:n]

# ───────────────────────────────────────────────
# ★ spec 正規化＋spec対応の語彙生成
# ───────────────────────────────────────────────
def _normalize_spec(picked, context_hint, audio_lang, words_env_count: int):
    if isinstance(picked, dict):
        theme = picked.get("theme") or "general vocabulary"
        ctx   = picked.get("context") or (context_hint or "")
        spec  = dict(picked)
        if "count" not in spec or not isinstance(spec["count"], int):
            spec["count"] = words_env_count
        return theme, ctx, spec
    if isinstance(picked, tuple) and len(picked) == 2:
        theme, ctx = picked[0], picked[1]
        spec = {"theme": theme, "context": ctx or (context_hint or ""), "count": words_env_count}
        return theme, ctx, spec
    theme = str(picked)
    ctx   = context_hint or ""
    spec = {"theme": theme, "context": ctx, "count": words_env_count}
    return theme, ctx, spec

# ───────────────────────────────────────────────
# 日本語TTS用ふりがな（語・文）
# ───────────────────────────────────────────────
_KANJI_ONLY = re.compile(r"^[一-龥々]+$")
_PARENS_JA  = re.compile(r"\s*[\(\（][^)\）]{1,40}[\)\）]\s*")
_KANJI_CHAR = re.compile(r"[一-龥々]")

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
            temperature=0.0, top_p=1.0,
        )
        yomi = (rsp.choices[0].message.content or "").strip()
        yomi = re.sub(r"[^ぁ-ゖゝゞー]+", "", yomi)
        return yomi[:20]
    except Exception:
        return ""

def _kanji_ratio(s: str) -> float:
    t = re.sub(r"[ \t\u3000]", "", s or "")
    if not t:
        return 0.0
    kan = len(_KANJI_CHAR.findall(t))
    return kan / max(1, len(t))

def _kana_reading_sentence(text: str) -> str:
    src = (text or "").strip()
    if not src:
        return ""
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role":"user",
                "content":(
                    "次の日本語の文を、そのままの意味で **ひらがなだけ** に直して返してください。"
                    "句読点（、。！？）はそのまま残してかまいません。"
                    "カタカナ・漢字・英字・数字・記号は使わないでください。\n\n"
                    f"文: {src}"
                )
            }],
            temperature=0.0, top_p=1.0,
        )
        out = (rsp.choices[0].message.content or "").strip()
        out = re.sub(r"[^ぁ-ゖゝゞー、。！？\s]+", "", out)
        out = _normalize_spaces(out)
        if out and not re.search(r"[。.!?！？]$", out):
            out += "。"
        return out
    except Exception:
        return ""

# ───────────────────────────────────────────────
# 例文取得（同じ3行ブロックの3行目）
# ───────────────────────────────────────────────
def _example_for_index(valid_dialogue: list[tuple[str, str]], idx0: int) -> str:
    role_idx = idx0 % 3
    base = idx0 - role_idx
    ex_pos = base + 2
    if 0 <= ex_pos < len(valid_dialogue):
        return valid_dialogue[ex_pos][1]
    return ""

def _safeify_trend_title(theme: str, lang: str) -> str:
    risk_words = [
        "war","attack","sex","murder","killed","politics","election","vote","president",
        "trump","biden","putin","israel","gaza","palestine","covid","vaccine","virus",
        "drug","explosion","shooting","scandal","accident","terror","suicide","death",
        "earthquake","tsunami","hurricane","flood","protest","riot","bomb","hostage"
    ]
    text = theme.strip().lower()
    risky = any(word in text for word in risk_words)
    if not risky:
        return theme
    safe_titles = {
        "ja": "最近のニュースを題材にした語彙学習",
        "en": "Vocabulary from recent news topics",
        "ko": "최근 뉴스 주제에서 배우는 어휘",
        "es": "Vocabulario de temas de actualidad",
        "fr": "Vocabulaire à partir des sujets d’actualité",
        "pt": "Vocabulário de tópicos recentes de notícias",
        "id": "Kosakata dari topik berita terkini",
    }
    return safe_titles.get(lang, safe_titles["en"])

# ───────────────────────────────────────────────
# 単語専用・文脈つき翻訳（1語だけ返す）
# ───────────────────────────────────────────────
def translate_word_context(word: str, target_lang: str, src_lang: str, theme: str, example: str, pos_hint: str | None = None) -> str:
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
        "- The output must be written entirely in the target language.",
        f"- Return ONLY one word in {LANG_NAME.get(target_lang,'target language')} language.",
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
    import re
    ONE_MIN_TAG = {
        "ja": " 1分学習",
        "en": " 1 min vocabulary",
        "es": " 1 min vocabulario",
        "fr": " 1 min vocabulaire",
        "pt": " 1 min vocabulário",
        "id": " 1 menit kosakata",
        "ko": " 1분 어휘",
    }

    if title_lang not in LANG_NAME:
        title_lang = "en"
    max_len = int(os.getenv("TITLE_MAX_JA", "28")) if title_lang == "ja" else int(os.getenv("TITLE_MAX_OTHER", "55"))

    try:
        theme_local = theme if title_lang == "en" else translate(theme, title_lang)
    except Exception:
        theme_local = theme

    theme_local = _safeify_trend_title(theme_local, title_lang)

    prefix = ""
    if title_lang == "ja":
        label = JP_CONV_LABEL.get((audio_lang_for_label or "").strip(), "")
        if label:
            prefix = f"{label} "

    def _smart_trim(s: str, lim: int) -> str:
        if len(s) <= lim:
            return s
        s = s[:lim]
        return re.sub(r"[ \u3000・、。!！?？:：\-–—｜|]+$", "", s)

    style = os.getenv("TITLE_STYLE", "random").lower()
    if   style == "classic": mode = 0
    elif style == "fixed":   mode = 1
    else:
        mode = random.choice([0, 1])

    def _fixed_1min() -> str:
        tag = ONE_MIN_TAG.get(title_lang, "~1 min vocabulary")
        if title_lang == "ja":
            t = f"{prefix}{sanitize_title(theme_local)}｜{tag}"
        else:
            t = f"{sanitize_title(theme_local)} | {tag}"
        return _smart_trim(sanitize_title(t), max_len)

    def _classic() -> str:
        try:
            lang_name = LANG_NAME.get(title_lang, "English")
            style_hint = "Keep it simple, catchy, and useful for learners. No emojis, no quotes."
            if title_lang == "ja":
                style_hint += " Start the title exactly with the given prefix. Keep consistent phrasing."

            prompt = (
                f"Generate ONE short YouTube title in {lang_name} for a vocabulary-learning short.\n"
                f"Theme: {theme_local}\n"
                f"Max characters: {max_len}\n"
                f"{style_hint}\n"
            )
            if prefix:
                prompt += f"Prefix (must appear at the very beginning): '{prefix}'\n"

            rsp = GPT.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0, top_p=1.0,
            )
            t = (rsp.choices[0].message.content or "").strip()
            t = sanitize_title(t)
            if title_lang == "ja" and prefix and not t.startswith(prefix):
                t = prefix + t
            t = _smart_trim(t, max_len)
            if len(t) < 4:
                raise ValueError("too short")
            return t
        except Exception:
            if title_lang == "ja":
                base = f"{theme_local} で使える一言"
                t = (prefix + base) if prefix and not base.startswith(prefix) else base
                return _smart_trim(sanitize_title(t), max_len)
            if title_lang == "en":
                t = f"{theme_local.capitalize()} vocab in one minute"
            else:
                t = f"{theme_local} vocabulary"
            return _smart_trim(sanitize_title(t), max_len)

    return _fixed_1min() if mode == 1 else _classic()

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

def _make_trend_context(theme: str, lang_code: str) -> str:
    theme = (theme or "").strip()
    if not theme:
        return ""
    if lang_code == "ja":
        return (
            f"今この話題（{theme}）について友達と雑談。予定や感想、場所や時間、チケット、混雑、"
            "ニュースで見た内容などを自然に話す。専門用語は避けて、日常会話でよく使う語を優先。"
        )
    elif lang_code == "en":
        return (
            f"Casual small talk about '{theme}': plans, opinions, tickets, time, place, "
            "what you saw on the news. Prefer everyday words and useful collocations."
        )
    elif lang_code == "es":
        return (
            f"Conversación informal sobre '{theme}': planes, opiniones, entradas, horarios y lugar. "
            "Usa palabras cotidianas y colocaciones frecuentes."
        )
    elif lang_code == "fr":
        return (
            f"Petite discussion sur '{theme}': projets, avis, billets, horaires, lieu. "
            "Privilégier le vocabulaire courant et les collocations utiles."
        )
    elif lang_code == "pt":
        return (
            f"Bate-papo sobre '{theme}': planos, opinião, ingressos, horário e local. "
            "Prefira palavras do dia a dia e colocações frequentes."
        )
    elif lang_code == "id":
        return (
            f"Obrolan santai tentang '{theme}': rencana, pendapat, tiket, waktu, tempat. "
            "Gunakan kosakata sehari-hari dan kolokasi umum."
        )
    elif lang_code == "ko":
        return (
            f"'{theme}'에 대해 가볍게 대화: 계획, 의견, 티켓, 시간, 장소. "
            "일상적으로 자주 쓰는 표현과 연어를 우선한다."
        )
    return f"Casual talk about '{theme}' with everyday words (plans, opinions, tickets, time, place)."

def make_tags(theme, audio_lang, subs, title_lang):
    LOCALIZED_TAGS = {
        "ja": ["語彙", "単語学習", "リスニング練習", "スピーキング練習", "字幕"],
        "en": ["vocabulary", "language learning", "speaking practice", "listening practice", "subtitles"],
        "es": ["vocabulario", "aprendizaje de idiomas", "práctica oral", "práctica auditiva", "subtítulos"],
        "fr": ["vocabulaire", "apprentissage des langues", "pratique orale", "écoute", "sous-titres"],
        "pt": ["vocabulário", "aprendizado de idiomas", "prática de fala", "prática auditiva", "legendas"],
        "id": ["kosakata", "belajar bahasa", "latihan berbicara", "latihan mendengarkan", "subtitle"],
        "ko": ["어휘", "언어 학습", "말하기 연습", "듣기 연습", "자막"],
    }

    base_tags = LOCALIZED_TAGS.get(title_lang, LOCALIZED_TAGS["en"]).copy()

    try:
        theme_local = theme if title_lang == "en" else translate(theme, title_lang)
    except Exception:
        theme_local = theme
    base_tags.insert(0, theme_local)

    for code in subs:
        if code in LANG_NAME:
            if title_lang == "ja":
                base_tags.append(f"{LANG_NAME[code]} 字幕")
            else:
                base_tags.append(f"{LANG_NAME[code]} subtitles")

    seen, out = set(), []
    for t in base_tags:
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
        local_context = ""
    else:
        if isinstance(spec, dict):
            theme = spec.get("theme") or topic
            local_context = (spec.get("context") or context_hint or "")
            vocab_words = _gen_vocab_list_from_spec(spec, audio_lang)
            try:
                (TEMP / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        else:
            theme = topic
            vocab_words = _gen_vocab_list(theme, audio_lang, words_count)
            local_context = context_hint or ""

    # 直近履歴保存（被り抑制の学習用）
    try:
        _save_history({
            "ts": time.time(),
            "audio_lang": audio_lang,
            "theme": theme,
            "words": list(dict.fromkeys(vocab_words)),  # 重複除去して順序維持
        })
    except Exception as e:
        logging.warning(f"[VARIETY] history save failed: {e}")

    # 3行ブロック: 単語 → 単語 → 例文
    dialogue = []
    for w in vocab_words:
        diff = (spec.get("difficulty") if isinstance(spec, dict) else None)
        ex = _gen_example_sentence(w, audio_lang, local_context, difficulty=diff)
        dialogue.extend([("N", w), ("N", w), ("N", ex)])

    valid_dialogue = [(spk, line) for (spk, line) in dialogue if line.strip()]
    audio_parts, sub_rows = [], [[] for _ in subs]
    plain_lines, tts_lines = [line for (_, line) in valid_dialogue], []

    # === フック ===
    hook_text = None
    hook_offset = 0
    if HOOK_ENABLE:
        theme_for_hook = theme if isinstance(theme, str) and theme else "everyday phrases – a simple situation"
        pattern_hint   = (spec.get("pattern_hint") if isinstance(spec, dict) else None)
        try:
            hook_text = generate_hook(theme_for_hook, audio_lang, pattern_hint)
        except Exception:
            hook_text = None
        if hook_text:
            valid_dialogue.insert(0, ("N", hook_text))
            hook_offset = 1

    # TTS & 字幕
    for i, (spk, line) in enumerate(valid_dialogue, 1):
        if hook_offset == 1 and i == 1:
            role_idx = -1
        else:
            role_idx = (i - 1 - hook_offset) % 3

        # ----- TTS -----
        tts_line = line
        if audio_lang == "ja":
            if role_idx in (2, -1):
                base_ex = _PARENS_JA.sub(" ", tts_line).strip()
                base_ex = _ensure_period_for_sentence(base_ex, audio_lang)
                do_kana = False
                if JA_EX_READING == "on":
                    do_kana = True
                elif JA_EX_READING == "auto":
                    if 2 <= len(base_ex) <= JA_EX_READING_MAX_LEN and _kanji_ratio(base_ex) >= JA_EX_READING_KANJI_RATIO:
                        do_kana = True
                tts_line = (_kana_reading_sentence(base_ex) or base_ex) if do_kana else base_ex
            else:
                if _KANJI_ONLY.fullmatch(line):
                    yomi = _kana_reading(line)
                    if yomi:
                        tts_line = yomi
                base = re.sub(r"[。！？!?]+$", "", tts_line).strip()
                tts_line = base + "。" if len(base) >= 2 else base
        else:
            if role_idx in (2, -1):
                tts_line = _ensure_period_for_sentence(tts_line, audio_lang)

        out_audio = TEMP / f"{i:02d}.wav"
        style_for_tts = HOOK_STYLE if role_idx == -1 else ("serious" if audio_lang == "ja" else "neutral")
        speak(audio_lang, spk, tts_line, out_audio, style=style_for_tts)
        audio_parts.append(out_audio)
        tts_lines.append(tts_line)

        # ----- 字幕 -----
        for r, lang in enumerate(subs):
            if role_idx == -1:
                if lang == audio_lang:
                    sub_rows[r].append(_clean_sub_line_hook(line, lang))
                else:
                    try:
                        trans = translate_sentence_strict(
                            line,
                            src_lang=audio_lang,
                            target_lang=lang,
                            max_sents=2,
                            max_len=120
                        )
                    except Exception:
                        trans = line
                    sub_rows[r].append(_clean_sub_line_hook(trans, lang))
                continue

            if lang == audio_lang:
                sub_rows[r].append(_clean_sub_line(line, lang))
            else:
                try:
                    if role_idx in (0, 1):
                        example_ctx = _example_for_index(valid_dialogue, i-1)
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
                        trans = translate_sentence_strict(
                            line,
                            src_lang=audio_lang,
                            target_lang=lang,
                            max_sents=1,
                            max_len=120
                        )
                except Exception:
                    trans = line
                sub_rows[r].append(_clean_sub_line(trans, lang))

    # 単純結合 → 整音 → mp3
    gap_ms = GAP_MS_JA if audio_lang == "ja" else GAP_MS
    pre_ms = PRE_SIL_MS_JA if audio_lang == "ja" else PRE_SIL_MS
    min_ms = MIN_UTTER_MS_JA if audio_lang == "ja" else MIN_UTTER_MS

    new_durs = _concat_with_gaps(audio_parts, gap_ms=gap_ms, pre_ms=pre_ms, min_ms=min_ms)
    enhance(TEMP/"full_raw.wav", TEMP/"full.wav")
    AudioSegment.from_file(TEMP/"full.wav").export(TEMP/"full.mp3", format="mp3")

    # 背景画像
    bg_png = TEMP / "bg.png"
    try:
        theme_en = translate(theme, "en")
    except Exception:
        theme_en = theme
    first_word = valid_dialogue[0][1] if valid_dialogue else theme

    def _is_ascii(s: str) -> bool:
        try:
            s.encode("ascii"); return True
        except Exception:
            return False

    if not _is_ascii(first_word or ""):
        query_for_bg = theme_en or "language learning"
    else:
        query_for_bg = first_word or theme_en or "learning"

    try:
        fetch_bg(query_for_bg, bg_png)
        if not bg_png.exists():
            raise FileNotFoundError("bg.png not created by fetch_bg")
    except Exception:
        try:
            from PIL import Image
            Image.new("RGB", (1920, 1080), (240, 240, 240)).save(bg_png)
        except Exception as e:
            raise RuntimeError(f"Failed to prepare bg.png fallback: {e}")

    # lines.json
    lines_data = []
    for i, ((spk, txt), dur) in enumerate(zip(valid_dialogue, new_durs)):
        row = [spk]
        for r in range(len(subs)):
            row.append(sub_rows[r][i])
        row.append(dur)
        lines_data.append(row)
    (TEMP/"lines.json").write_text(json.dumps(lines_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # デバッグ
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

    needed = {
        "lines.json": TEMP/"lines.json",
        "full.mp3":   TEMP/"full.mp3",
        "bg.png":     bg_png,
    }
    missing = [k for k,p in needed.items() if not p.exists()]
    if missing:
        raise RuntimeError(f"❌ 必要なファイルが見つかりません: {', '.join(missing)}")

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
                if _is_limit_error(e):
                    logging.warning(f"[UPLOAD] ⚠️ limit reached on account='{acc}' → trying next fallback.")
                    continue
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
                logging.exception(f"[UPLOAD] unexpected error on account='{acc}'")
                raise

        msg = f"Upload skipped due to per-account limits. tried={tried}"
        logging.warning("[UPLOAD] " + msg)
        try:
            (TEMP / "UPLOAD_SKIPPED.txt").write_text(msg, encoding="utf-8")
        except Exception:
            pass
        return False

    _try_upload_with_fallbacks()

def _gen_vocab_list(theme: str, lang_code: str, n: int) -> list[str]:
    spec = {
        "theme": theme,
        "context": _make_trend_context(theme, lang_code),
        "count": n,
    }
    return _gen_vocab_list_from_spec(spec, lang_code)

# ───────────────────────────────────────────────
def run_all(topic, turns, privacy, do_upload, chunk_size):
    """
    親プロセス: 各 account ごとに子プロセスを起動（ISOLATED_RUN=1 を付与）
    子プロセス(ISOLATED_RUN=1): そのまま run_one を実行（再帰起動しない）
    """
    isolated = os.getenv("ISOLATED_RUN", "0") == "1"

    if isolated:
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

            # AUTO_TREND
            if topic.strip().upper() == "AUTO_TREND":
                try:
                    from topic_picker import build_trend_spec
                    TREND_DIR = TEMP / "trends"

                    trend_lang = subs[1] if len(subs) > 1 else audio_lang

                    candidates = get_trend_candidates(
                        audio_lang=trend_lang,
                        cache_dir=TREND_DIR,
                        limit=30,
                        cache_ttl_minutes=60,
                    )
                    if not candidates:
                        raise ValueError("no candidates")

                    today = int(dt.datetime.utcnow().strftime("%Y%m%d"))
                    idx = (hash((trend_lang, today)) % len(candidates))
                    picked_topic = candidates[idx]
                    # ★ 直近テーマ回避（候補から差し替え）
                    picked_topic = _avoid_recent_theme(picked_topic, candidates, audio_lang)

                    spec_for_run = build_trend_spec(
                        theme=picked_topic,
                        audio_lang=audio_lang,
                        count=int(os.getenv("VOCAB_WORDS", "6")),
                    )
                    context_hint = spec_for_run.get("context", "")

                    logging.info(
                        f"[TREND] trend_lang={trend_lang} → picked='{picked_topic}' "
                        f"(#{idx+1}/{len(candidates)})"
                    )

                    try:
                        TREND_DIR.mkdir(parents=True, exist_ok=True)
                        with open(TREND_DIR / f"picked_{trend_lang}.txt", "w", encoding="utf-8") as f:
                            f.write("picked: " + picked_topic + "\n\n")
                            f.write("\n".join(candidates[:20]))
                    except Exception:
                        pass

                except Exception as e:
                    logging.warning(f"[TREND] failed ({e}) → fallback to AUTO.")
                    topic = "AUTO"

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
                # ★ 直近テーマに当たったら最大 THEME_REGEN_ATTEMPTS 回まで引き直し
                recent_themes, _ = _recent_themes(audio_lang)
                tries = 0
                while picked_topic in recent_themes and tries < THEME_REGEN_ATTEMPTS:
                    tries += 1
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
        env["ISOLATED_RUN"] = "1"

        logging.info(f"▶ Spawning isolated run for account={account}: {' '.join(cmd)}")
        subprocess.run(cmd, check=False, env=env)

# ───────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="語彙テーマ。AUTO＝自動、AUTO_TREND＝最新トレンドから取得。カンマ/改行区切りなら単語リスト。")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--privacy", default="unlisted", choices=["public","unlisted","private"])
    ap.add_argument("--lines-only", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--chunk", type=int, default=9999, help="Shortsは分割せず1本推奨")
    ap.add_argument("--account", type=str, default="", help="この account のみ実行（combos.yaml の account 値に一致）")
    args = ap.parse_args()

    target_cli = (args.account or "").strip()
    target_env = os.getenv("TARGET_ACCOUNT", "").strip()
    TARGET_ONLY = target_cli or target_env

    if TARGET_ONLY:
        selected = [c for c in COMBOS if c.get("account", "default") == TARGET_ONLY]
        if not selected:
            logging.error(f"[ABORT] No combos matched account='{TARGET_ONLY}'. Check combos.yaml.")
            raise SystemExit(2)
        COMBOS[:] = selected
        logging.info(f"[ACCOUNT FILTER] Running only for account='{TARGET_ONLY}' ({len(COMBOS)} combo(s)).")

    topic = resolve_topic(args.topic)
    run_all(topic, args.turns, args.privacy, not args.no_upload, args.chunk)