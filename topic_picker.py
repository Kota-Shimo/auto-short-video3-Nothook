# topic_picker.py – AUTOの多様化 & 日替わり固定 + 会話視点 (speaker/listener)
import os, json, hashlib, datetime as dt, re, random, secrets
from pathlib import Path
from typing import Any
from config import TEMP

# ========= 基本設定 =========
RECENT_BLOCK_N = int(os.getenv("RECENT_BLOCK_N", "7"))      # 直近ブロック数
DIFF_LEVEL     = os.getenv("DIFF_LEVEL", "A2")              # A1/A2/B1/B2
WORDS_DEFAULT  = int(os.getenv("VOCAB_WORDS", "6"))         # 単語数
DAILY_LOCK     = os.getenv("TOPIC_DAILY", "1") == "1"       # 日替わり固定（※現行は未使用）
ROLE_MODE      = os.getenv("ROLE_MODE", "rotate")           # fixed / rotate / random

# ========= テーマ候補プール =========
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

# ========= 各シーンに対応する視点ペア =========
ROLE_MAP = {
    "restaurant": ("customer", "waiter"),
    "cafe": ("customer", "barista"),
    "hotel": ("guest", "receptionist"),
    "train": ("traveler", "station staff"),
    "airport": ("traveler", "staff"),
    "shop": ("customer", "clerk"),
    "pharmacy": ("customer", "pharmacist"),
    "doctor": ("patient", "receptionist"),
    "work": ("colleague", "colleague"),
    "gym": ("member", "trainer"),
    "sns": ("friend", "friend"),
    "weather": ("friend", "friend"),
    "reservation": ("customer", "operator"),
    "lost": ("traveler", "staff"),
    "photo": ("traveler", "local"),
}

# ========= 類似テーマ判定 =========
KEYMAP = {
    "restaurant": ["restaurant","order","menu","request","polite"],
    "cafe":       ["cafe","coffee","order"],
    "hotel":      ["hotel","check-in","check-out","room","reception"],
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

# ========= 最近テーマ保存 =========
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
    ka, kb = _keyset(a), _keyset(b)
    if ka & kb:
        return True
    wa, wb = set(re.findall(r"[a-z]+", a.lower())), set(re.findall(r"[a-z]+", b.lower()))
    return len(wa & wb) >= 3

# ========= 日替わりシード（参考：現行は使わない） =========
def _daily_seed(lang: str) -> int:
    today = dt.datetime.utcnow().strftime("%Y%m%d")
    base = f"{lang}:{today}:{os.getenv('TOPIC_SALT','v1')}"
    return int(hashlib.sha256(base.encode()).hexdigest(), 16) % (10**9)

# ========= 視点ローテーション選択 =========
def _pick_role_for(theme: str) -> tuple[str, str]:
    s = theme.lower()
    for k, v in ROLE_MAP.items():
        if k in s:
            return v
    # default: friend↔friend
    return ("friend", "friend")

# ========= AUTOテーマ選択（完全ランダム化） =========
def _pick_theme_for(lang: str) -> str:
    recent = _load_recent(lang)

    # ✅ 完全ランダム（毎回違う乱数源）
    rnd = random.Random(secrets.randbits(64))

    candidates = POOL[:]
    rnd.shuffle(candidates)

    for t in candidates:
        if all(not _too_similar(t, r) for r in recent[-RECENT_BLOCK_N:]):
            _save_recent(lang, t)
            return t

    t = "everyday small talk"
    _save_recent(lang, t)
    return t

# ========= context生成 =========
def _make_context(theme: str, lang: str, speaker: str, listener: str) -> str:
    if lang == "ja":
        return (
            f"{speaker}が{listener}に話す場面。テーマは「{theme}」。"
            "予定や感想、時間や場所など、短く自然にやり取りする。"
            "専門用語は避け、日常でよく使う語を優先。"
        )
    return (
        f"A short, natural conversation where a {speaker} speaks to a {listener} "
        f"about '{theme}'. Include small requests, opinions, or confirmations. Prefer everyday language."
    )

# ========= patternヒント補強 =========
def _pattern_hint_for(theme: str, speaker: str, listener: str) -> str:
    s = theme.lower()
    if "restaurant" in s or "cafe" in s:
        if speaker == "customer":
            return "ordering, asking politely, follow-up requests"
        else:
            return "offering, confirming, suggesting options"
    if "hotel" in s:
        if speaker == "guest":
            return "check-in, confirming details, asking politely"
        else:
            return "welcoming, explaining, offering help"
    if "train" in s or "station" in s or "airport" in s:
        return "asking time and place, tickets, directions, confirming details"
    if "shopping" in s or "price" in s or "payment" in s:
        if speaker == "customer":
            return "asking price, options, short reasons"
        else:
            return "explaining options, confirming total, politeness"
    return "short natural exchanges, opinions, confirmations"

# ========= トレンドspec =========
def build_trend_spec(theme: str, audio_lang: str, count: int | None = None) -> dict[str, Any]:
    c = int(count or WORDS_DEFAULT)
    sp, ls = _pick_role_for(theme)
    return {
        "theme": theme,
        "context": (
            f"Casual talk between {sp} and {ls} about '{theme}', including plans, tickets, and opinions. [TREND]"
            if audio_lang != "ja" else
            f"{sp}が{ls}に{theme}について話す日常会話。[TREND]"
        ),
        "count": c,
        "relation_mode": "contextual",
        "pos": ["noun","verb"],
        "difficulty": DIFF_LEVEL,
        "trend": True,
        "speaker": sp,
        "listener": ls,
    }

# ========= AUTO本体 =========
def pick_by_content_type(content_mode: str, audio_lang: str, return_context: bool = False):
    if content_mode != "vocab":
        theme = _pick_theme_for(audio_lang)
        sp, ls = _pick_role_for(theme)
        return (theme, _make_context(theme, audio_lang, sp, ls)) if return_context else theme

    theme = _pick_theme_for(audio_lang)
    sp, ls = _pick_role_for(theme)

    spec = {
        "theme": theme,
        "context": _make_context(theme, audio_lang, sp, ls),
        "count": WORDS_DEFAULT,
        "relation_mode": "contextual",
        "pos": ["noun","verb"],
        "difficulty": DIFF_LEVEL,
        "pattern_hint": _pattern_hint_for(theme, sp, ls),
        "trend": False,
        "speaker": sp,
        "listener": ls,
    }
    return spec if return_context else theme