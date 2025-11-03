# topic_picker.py – AUTOの多様化 & 日替わり固定（main.pyは変更不要）
import os, json, hashlib, datetime as dt, re, random
from pathlib import Path
from typing import Any
from config import TEMP

# ========= 基本設定（必要ならENVで調整） =========
RECENT_BLOCK_N = int(os.getenv("RECENT_BLOCK_N", "7"))      # 直近ブロック数
DIFF_LEVEL     = os.getenv("DIFF_LEVEL", "A2")              # A1/A2/B1/B2
WORDS_DEFAULT  = int(os.getenv("VOCAB_WORDS", "6"))         # 単語数
DAILY_LOCK     = os.getenv("TOPIC_DAILY", "1") == "1"       # 日替わり固定を有効

# ========= テーマ候補プール（学習向けに高頻度&再利用性） =========
POOL = [
    # 接客・旅行
    "hotel check-in small talk","polite requests at a restaurant","ordering coffee at a cafe",
    "asking for directions in a station","train tickets and platforms","airport check-in basics",
    "asking about opening hours","making a reservation by phone","confirming a booking",
    "check-out phrases","lost and found basics","simple troubleshooting at a counter",
    # 日常会話
    "weather and weekend plans","small talk at workplace","hobbies and free time",
    "giving short compliments","simple apologies and excuses","asking availability",
    "inviting and declining politely","giving short instructions","following up politely",
    # 買い物・支払
    "convenience store shopping","asking price and payment options","refunds and exchanges",
    "membership and points","delivery and pickup options",
    # 生活・健康
    "gym and health routine","simple doctor reception phrases","pharmacy basics",
    # SNS/IT
    "sharing photos and links","simple app troubleshooting",
    # 観光
    "tickets and time for attractions","photo spots and recommendations",
]

# ========= 類似判定（同系統連発を避けるための軽量フィルタ） =========
KEYMAP = {
    "restaurant": ["restaurant","order","menu","request","polite","could","may"],
    "cafe":       ["cafe","coffee","order"],
    "hotel":      ["hotel","check-in","check-out","room","reception","upgrade"],
    "train":      ["train","station","platform","ticket"],
    "airport":    ["airport","flight","check-in"],
    "work":       ["workplace","follow up","instruction"],
    "shop":       ["shopping","store","price","refund","exchange","payment"],
}

def _keyset(t: str) -> set[str]:
    s = t.lower()
    keys = set()
    for k, words in KEYMAP.items():
        if any(w in s for w in words):
            keys.add(k)
    return keys

# ========= 最近テーマの保存/読込（言語別） =========
def _recent_path(lang: str) -> Path:
    p = TEMP / f"recent_topics_{lang}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _load_recent(lang: str) -> list[str]:
    try:
        return json.loads(_recent_path(lang).read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_recent(lang: str, topic: str):
    lst = [x for x in _load_recent(lang) if x] + [topic]
    if len(lst) > RECENT_BLOCK_N:
        lst = lst[-RECENT_BLOCK_N:]
    _recent_path(lang).write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")

def _too_similar(a: str, b: str) -> bool:
    # キーワード群が重なる＆単語オーバーラップが多い場合に似ているとみなす
    ka, kb = _keyset(a), _keyset(b)
    if ka & kb:
        return True
    wa, wb = set(re.findall(r"[a-z]+", a.lower())), set(re.findall(r"[a-z]+", b.lower()))
    return len(wa & wb) >= 3

# ========= 日替わりシード =========
def _daily_seed(lang: str) -> int:
    if not DAILY_LOCK:
        # 乱数に任せる（ワークフローごとに変わりうる）
        return random.randint(0, 10**9)
    today = dt.datetime.utcnow().strftime("%Y%m%d")
    base = f"{lang}:{today}:{os.getenv('TOPIC_SALT','v1')}"
    return int(hashlib.sha256(base.encode()).hexdigest(), 16) % (10**9)

# ========= テーマ選択（AUTO用） =========
def _pick_theme_for(lang: str) -> str:
    recent = _load_recent(lang)
    seed = _daily_seed(lang)
    rnd = random.Random(seed)
    # 候補をランダム順に並べ、最近と「似すぎ」を除外
    candidates = POOL[:]
    rnd.shuffle(candidates)
    for t in candidates:
        if all(not _too_similar(t, r) for r in recent[-RECENT_BLOCK_N:]):
            _save_recent(lang, t)
            return t
    # どうしてもダメならシンプルな汎用テーマ
    t = "everyday small talk"
    _save_recent(lang, t)
    return t

# ========= トレンド専用のspec（main.pyから呼ばれてもOKなダミー実装） =========
def build_trend_spec(theme: str, audio_lang: str, count: int | None = None) -> dict[str, Any]:
    c = int(count or WORDS_DEFAULT)
    return {
        "theme": theme,
        "context": (
            f"Casual small talk about '{theme}': plans, opinions, tickets, time, place. "
            "Prefer everyday words and useful collocations. [TREND]"
            if audio_lang != "ja" else
            f"今の話題（{theme}）について日常会話。予定・感想・時間・場所・チケットなどを自然に話す。[TREND]"
        ),
        "count": c,
        "relation_mode": "contextual",
        "pos": ["noun","verb"],       # モーダル連発を避ける
        "difficulty": DIFF_LEVEL,
        "trend": True
    }

# ========= AUTO本体 =========
def pick_by_content_type(content_mode: str, audio_lang: str, return_context: bool = False):
    """
    戻り値:
      - return_context=False: 文字列テーマ
      - return_context=True : (spec辞書) を返す（main.py 側の _normalize_spec が吸収可能）
    """
    if content_mode != "vocab":
        # vocab以外はシンプルなフォールバック
        theme = _pick_theme_for(audio_lang)
        return (theme, _make_context(theme, audio_lang)) if return_context else theme

    theme = _pick_theme_for(audio_lang)

    # ★ “contextual & noun/verb” を明示（could/may偏りの抑制）
    spec = {
        "theme": theme,
        "context": _make_context(theme, audio_lang),
        "count": WORDS_DEFAULT,
        "relation_mode": "contextual",
        "pos": ["noun","verb"],
        "difficulty": DIFF_LEVEL,
        "pattern_hint": _pattern_hint_for(theme),
        "trend": False,
    }
    return spec if return_context else theme

# ========= ユーティリティ =========
def _make_context(theme: str, lang: str) -> str:
    if lang == "ja":
        return (
            f"この話題（{theme}）について短く自然に雑談。予定や感想、時間や場所、チケット、支払いなど。"
            "専門用語は避け、日常でよく使う語を優先。"
        )
    return (
        f"Casual small talk about '{theme}': plans, opinions, time and place, "
        "tickets and payment, simple reasons. Prefer everyday words."
    )

def _pattern_hint_for(theme: str) -> str:
    s = theme.lower()
    if "restaurant" in s or "cafe" in s:
        return "ordering, asking politely, follow-up requests"
    if "hotel" in s:
        return "check-in, confirming details, offering help"
    if "train" in s or "station" in s or "airport" in s:
        return "asking time and place, tickets, directions"
    if "shopping" in s or "price" in s or "payment" in s:
        return "asking price, options, short reasons"
    return "small talk patterns, short reasons, simple opinions"