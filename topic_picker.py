# topic_picker.py – Shorts最適化・決定版（main.py互換）
# 目的:
#  - 日×アカウント×音声言語で安定した題材（検証容易）
#  - 学習者L1×Targetに最適化（刺さるFunctional/Sceneへ加点）
#  - 感情トリガー付きの“具体場面”を自動付与（hookとの整合性UP）
#  - パターン（構文）自動割当で学習リワード明確化
#  - 季節/曜日ブースト、トレンド対応、演出ヒント/学習約束テキスト付

import os
import json
import random
import hashlib
from datetime import date
from typing import List, Tuple, Dict, Optional

# ─────────────────────────────────────────
# RNG: “決定的”シード（起動に依存しない）
# ─────────────────────────────────────────
def _select_rng() -> random.Random:
    deterministic = os.getenv("DETERMINISTIC_DAY", "1") != "0"
    if not deterministic:
        return random.SystemRandom()
    account = os.getenv("ACCOUNT") or os.getenv("TARGET_ACCOUNT") or ""
    audio   = os.getenv("AUDIO_LANG") or ""
    day     = date.today().isoformat()
    # Python組込hash()は起動ごとに変わる→SHA1で固定
    digest = hashlib.sha1(f"{account}|{audio}|{day}".encode("utf-8")).hexdigest()
    seed = int(digest, 16) % (2**32)
    return random.Random(seed)

rng = _select_rng()

# ========== 定義（ベース） ==========
FUNCTIONALS: List[str] = [
    "greetings & introductions",
    "numbers & prices",
    "time & dates",
    "asking & giving directions",
    "polite requests",
    "offers & suggestions",
    "clarifying & confirming",
    "describing problems",
    "apologizing & excuses",
    "agreeing & disagreeing",
    "preferences & opinions",
    "making plans",
    "past experiences",
    "future arrangements",
    "comparisons",
    "frequency & habits",
    "permission & ability",
    "cause & reason",
    "condition & advice",
    "small talk starters",
    "job interviews",
]

SCENES_BASE: List[str] = [
    "restaurant ordering",
    "shopping basics",
    "paying & receipts",
    "transport tickets",
    "street directions",
    "hotel check-in/out",
    "facilities & problems",
    "appointments",
    "phone basics",
    "returns & exchanges",
    "airport check-in",
    "security & boarding",
    "pharmacy basics",
    "delivery and online shopping",
    "addresses & contact info",
    "emergencies",
    "job interview",
    "small talk at lobby",
]

SCENES_BY_FUNCTIONAL: Dict[str, List[str]] = {
    "greetings & introductions": ["small talk at lobby", "phone basics", "restaurant ordering"],
    "numbers & prices": ["shopping basics", "paying & receipts", "transport tickets"],
    "time & dates": ["appointments", "transport tickets", "restaurant ordering"],
    "asking & giving directions": ["street directions", "transport tickets", "hotel check-in/out"],
    "polite requests": ["restaurant ordering", "hotel check-in/out", "facilities & problems"],
    "offers & suggestions": ["restaurant ordering", "making plans in lobby", "phone basics"],
    "clarifying & confirming": ["paying & receipts", "appointments", "security & boarding"],
    "describing problems": ["facilities & problems", "pharmacy basics", "returns & exchanges"],
    "apologizing & excuses": ["appointments", "restaurant ordering", "transport tickets"],
    "agreeing & disagreeing": ["making plans in lobby", "restaurant ordering"],
    "preferences & opinions": ["restaurant ordering", "shopping basics"],
    "making plans": ["appointments", "restaurant ordering", "phone basics"],
    "past experiences": ["small talk at lobby", "restaurant ordering"],
    "future arrangements": ["appointments", "transport tickets"],
    "comparisons": ["shopping basics", "restaurant ordering"],
    "frequency & habits": ["small talk at lobby", "pharmacy basics"],
    "permission & ability": ["security & boarding", "hotel check-in/out"],
    "cause & reason": ["returns & exchanges", "facilities & problems"],
    "condition & advice": ["pharmacy basics", "emergencies", "dietary needs"],
    "small talk starters": ["small talk at lobby", "restaurant ordering", "phone basics"],
    "job interviews": ["job interview", "appointments", "phone basics"],
}

# 学習者L1 推定：アカウント→L1
ACCOUNT_L1: Dict[str, str] = {
    "acc1": "pt", "acc2": "id", "acc3": "ja",
    "acc4": "ja", "acc5": "ja", "acc6": "ja",
    "acc7": "en", "acc8": "ja", "acc9": "pt",
}

# 言語ペアで刺さるFunctional/Sceneに加点
FUNCTIONAL_WEIGHTS_BY_LANGPAIR: Dict[Tuple[str, str], Dict[str, int]] = {
    ("ja","en"): {"polite requests": 3, "asking & giving directions": 2, "numbers & prices": 2, "time & dates": 1},
    ("id","en"): {"polite requests": 2, "time & dates": 1, "clarifying & confirming": 1},
    ("pt","en"): {"polite requests": 3, "clarifying & confirming": 2},
    ("en","ja"): {"polite requests": 3, "asking & giving directions": 2},
    ("en","ko"): {"polite requests": 3, "time & dates": 1},
    ("ja","ko"): {"polite requests": 2, "asking & giving directions": 1},
}

SCENE_WEIGHTS_BY_LANGPAIR: Dict[Tuple[str, str], Dict[str, int]] = {
    ("ja","en"): {"restaurant ordering": 3, "street directions": 2, "hotel check-in/out": 2, "shopping basics": 1},
    ("id","en"): {"shopping basics": 3, "paying & receipts": 2, "transport tickets": 1},
    ("pt","en"): {"restaurant ordering": 3, "paying & receipts": 2, "phone basics": 1},
    ("en","ja"): {"hotel check-in/out": 3, "street directions": 2, "restaurant ordering": 1},
    ("en","ko"): {"restaurant ordering": 2, "street directions": 2, "shopping basics": 1},
    ("ja","ko"): {"restaurant ordering": 2, "shopping basics": 1, "street directions": 1},
}

# 予約スロット（強テーマ保証）
RESERVED_PAIR_THEME: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("ja", "en"): ("polite requests", "restaurant ordering"),
    ("pt", "en"): ("polite requests", "restaurant ordering"),
    ("id", "en"): ("numbers & prices", "shopping basics"),
    ("en", "ja"): ("polite requests", "hotel check-in/out"),
    ("en", "ko"): ("polite requests", "restaurant ordering"),
    ("ja", "ko"): ("polite requests", "restaurant ordering"),
}

# ─────────────────────────────────────────
# 季節/曜日ブースト（需要波）
# ─────────────────────────────────────────
def _seasonal_scene_boost(scene: str) -> int:
    d = date.today(); w = d.weekday(); m = d.month
    if w in (5,6):  # 週末
        if any(k in scene for k in ("restaurant", "street directions", "hotel")):
            return 1
    if w == 0:  # 月曜
        if any(k in scene for k in ("appointments", "phone", "paying")):
            return 1
    if m in (11,12,1):  # 年末年始
        if any(k in scene for k in ("shopping", "paying", "transport")):
            return 1
    return 0

# ─────────────────────────────────────────
# 難易度重み（短尺で崩れにくいA2/B1寄せ）
# ─────────────────────────────────────────
FUNCTIONAL_WEIGHTS_BY_LEVEL: Dict[str, Dict[str, int]] = {
    "A1": {"greetings & introductions": 8, "numbers & prices": 7, "time & dates": 6,
           "polite requests": 5, "asking & giving directions": 6, "making plans": 4,
           "preferences & opinions": 3, "small talk starters": 3},
    "A2": {"greetings & introductions": 6, "numbers & prices": 5, "time & dates": 5,
           "polite requests": 6, "asking & giving directions": 6, "making plans": 5,
           "clarifying & confirming": 4, "preferences & opinions": 4, "small talk starters": 4,
           "describing problems": 3, "permission & ability": 3},
    "B1": {"clarifying & confirming": 6, "describing problems": 6,
           "condition & advice": 5, "cause & reason": 5, "agreeing & disagreeing": 4,
           "comparisons": 4, "past experiences": 3, "future arrangements": 3,
           "polite requests": 3, "making plans": 3, "job interviews": 5},
    "B2": {"agreeing & disagreeing": 6, "preferences & opinions": 6,
           "cause & reason": 5, "condition & advice": 5, "comparisons": 4,
           "clarifying & confirming": 4, "describing problems": 4, "job interviews": 6},
}

SCENE_WEIGHTS_BY_LEVEL: Dict[str, Dict[str, int]] = {
    "A1": {"shopping basics": 8, "restaurant ordering": 7, "paying & receipts": 6,
           "phone basics": 5, "addresses & contact info": 5, "transport tickets": 5,
           "hotel check-in/out": 4, "street directions": 6},
    "A2": {"restaurant ordering": 7, "shopping basics": 6, "paying & receipts": 6,
           "appointments": 5, "transport tickets": 5, "hotel check-in/out": 5,
           "facilities & problems": 4, "pharmacy basics": 4, "street directions": 6},
    "B1": {"facilities & problems": 6, "returns & exchanges": 6, "appointments": 5,
           "security & boarding": 5, "delivery and online shopping": 4, "pharmacy basics": 4,
           "job interview": 5},
    "B2": {"emergencies": 6, "security & boarding": 5, "returns & exchanges": 5,
           "facilities & problems": 5, "delivery and online shopping": 4, "job interview": 6},
}

# ─────────────────────────────────────────
# 感情トリガー付き “具体状況” → 例文方向性/Hook整合
# （scene名: [(日本語の心理状況, 英語の推奨例文の骨格), ...]）
# ─────────────────────────────────────────
EMOTIONAL_SCENES: Dict[str, List[Tuple[str, str]]] = {
    "restaurant ordering": [
        ("注文したのに来ない時", "Could you check my order, please?"),
        ("おすすめを聞きたい時", "What do you recommend?"),
        ("聞き返された時", "Sorry, could you say that again?"),
    ],
    "hotel check-in/out": [
        ("予約が見つからない時", "I think my booking might be missing."),
        ("部屋を変えたい時", "Could I change my room, please?"),
        ("チェックインが遅れた時", "Sorry, my flight was delayed."),
    ],
    "shopping basics": [
        ("値段を聞きたい時", "How much is this?"),
        ("色違いを探す時", "Do you have this in blue?"),
        ("サイズ違いを探す時", "Do you have a larger size?"),
    ],
    "street directions": [
        ("道が分からない時", "Excuse me, how can I get to ...?"),
        ("バスを逃した時", "When is the next bus to ...?"),
    ],
    "paying & receipts": [
        ("レシートが欲しい時", "Could I have a receipt, please?"),
        ("会計が違う時", "I think there’s a mistake in the bill."),
    ],
    "returns & exchanges": [
        ("交換したい時", "Could I exchange this, please?"),
        ("返品したい時", "I’d like to return this."),
    ],
    "phone basics": [
        ("聞き取れない時", "Sorry, could you speak a little slower?"),
        ("折り返しを頼む時", "Could you call me back later?"),
    ],
    "appointments": [
        ("予約を取りたい時", "I’d like to make an appointment."),
        ("時間を変えたい時", "Could I reschedule to tomorrow?"),
    ],
}

# ─────────────────────────────────────────
# 補助ユーティリティ
# ─────────────────────────────────────────
def _env_level() -> str:
    v = os.getenv("CEFR_LEVEL", "").strip().upper()
    return v if v in ("A1","A2","B1","B2") else "A2"

def _current_pair(audio_lang: str) -> Tuple[str, str]:
    audio = (audio_lang or "").lower()
    l1_override = os.getenv("L1_OVERRIDE", "").strip().lower()
    if l1_override:
        return (l1_override, audio)
    account = (os.getenv("ACCOUNT") or os.getenv("TARGET_ACCOUNT") or "").strip().lower()
    if account and account in ACCOUNT_L1:
        return (ACCOUNT_L1[account], audio)
    subs = os.getenv("SUBS", "")
    if subs:
        try:
            arr = [s.strip().lower() for s in subs.split(",") if s.strip()]
            for s in arr:
                if s != audio:
                    return (s, audio)
        except Exception:
            pass
    return ("", audio)

def _choose_weighted(items: List[Tuple[str, int]]) -> str:
    pool, weights = zip(*[(k, max(0, w)) for k, w in items if w > 0])
    return rng.choices(pool, weights=weights, k=1)[0]

def _weights_from_dict(keys: List[str], table: Dict[str, int]) -> List[Tuple[str, int]]:
    return [(k, table.get(k, 1)) for k in keys]

def _maybe_reserved(functional_weights: Dict[str, int], scene_candidates: List[str], l1: str, tgt: str):
    if os.getenv("RESERVED_FIRST", "1") == "0":
        return None
    key = (l1, tgt)
    if key not in RESERVED_PAIR_THEME: return None
    f, s = RESERVED_PAIR_THEME[key]
    if f in functional_weights and (s in scene_candidates or not scene_candidates):
        return (f, s)
    return None

# ─────────────────────────────────────────
# パターン（構文）ヒントの自動割当
# ─────────────────────────────────────────
def _pattern_for_scene(scene: str) -> str:
    s = (scene or "").lower()
    if "restaurant" in s: return "Could I / May I / I’d like to"
    if "hotel" in s:      return "I’d like to / Could I / Would it be possible to"
    if "shopping" in s:   return "Do you have / How much is / I’m looking for"
    if "street" in s:     return "Where is / How can I get to / Is there"
    if "paying" in s:     return "Could I have / I think there’s / Can I pay by"
    if "returns" in s:    return "I’d like to / Could I exchange / I bought this here"
    if "appointments" in s:return "I’d like to make / Could I reschedule / Are you available"
    if "phone" in s:      return "Could you speak / Could you call me back / May I talk to"
    if "transport" in s:  return "When is / Where can I buy / Does this go to"
    return "Polite request / Confirm detail"

# ─────────────────────────────────────────
# ピッカー（Functional → Scene → 情緒状況）
# ─────────────────────────────────────────
def _pick_functional(audio_lang: str) -> str:
    override = os.getenv("FUNCTIONAL_OVERRIDE", "").strip()
    if override:
        return override
    level = _env_level()
    weights = FUNCTIONAL_WEIGHTS_BY_LEVEL.get(level, {}).copy()
    l1, tgt = _current_pair(audio_lang)
    pair = (l1, tgt)
    if pair in FUNCTIONAL_WEIGHTS_BY_LANGPAIR:
        for k, v in FUNCTIONAL_WEIGHTS_BY_LANGPAIR[pair].items():
            weights[k] = max(1, weights.get(k, 1) + v)
    items = _weights_from_dict(FUNCTIONALS, weights)
    return _choose_weighted(items)

def _pick_scene(functional: str, audio_lang: str) -> str:
    override = os.getenv("SCENE_OVERRIDE", "").strip()
    if override:
        return override
    level = _env_level()
    base = SCENES_BY_FUNCTIONAL.get(functional, SCENES_BASE)
    level_weights = SCENE_WEIGHTS_BY_LEVEL.get(level, {})
    weights = {k: level_weights.get(k, 1) for k in base}
    l1, tgt = _current_pair(audio_lang)
    pair = (l1, tgt)
    if pair in SCENE_WEIGHTS_BY_LANGPAIR:
        for k, v in SCENE_WEIGHTS_BY_LANGPAIR[pair].items():
            if k in weights:
                weights[k] = max(1, weights.get(k, 1) + v)
    # プレミアム＆季節ブースト
    for k in list(weights.keys()):
        weights[k] += _seasonal_scene_boost(k)
        weights[k] = max(1, weights[k])
    items = list(weights.items())
    return _choose_weighted(items)

def _pick_emotional(scene: str) -> Optional[Tuple[str, str]]:
    arr = EMOTIONAL_SCENES.get(scene, [])
    if not arr: return None
    return rng.choice(arr)

# ─────────────────────────────────────────
# specビルド（main.py 互換）
# ─────────────────────────────────────────
def _random_pos_from_env_or_default() -> List[str]:
    v = os.getenv("VOCAB_POS", "").strip()
    if v:
        return [x.strip() for x in v.split(",") if x.strip()]
    return []

def _random_difficulty() -> str:
    env = os.getenv("CEFR_LEVEL", "").strip().upper()
    if env in ("A1","A2","B1","B2"):
        return env
    return rng.choice(["A2","B1","B2"])

def _parse_csv_env(name: str) -> List[str]:
    v = os.getenv(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]

def _context_for_theme(functional: str, scene: str, emotion_ja: Optional[str]) -> str:
    # 英語プロンプト用の短い“状況説明”＋（あれば）心理状況
    base = "A simple, practical conversation in everyday life. Be polite and clear."
    s = (scene or "").lower()
    if "restaurant" in s: base = "A customer orders food and asks a brief question politely."
    elif "hotel" in s:    base = "A guest talks to the front desk to make a simple request politely."
    elif "shopping" in s: base = "A customer asks for items, sizes or colors in a store."
    elif "street" in s:   base = "A person asks for directions and confirms a simple route."
    elif "paying" in s:   base = "A customer pays and asks for a receipt or clarifies the bill."
    elif "returns" in s:  base = "A customer politely asks to return or exchange an item."
    elif "appointments" in s: base = "A person makes or reschedules a simple appointment time."
    elif "phone" in s:    base = "A caller asks a simple question or requests a callback."
    if emotion_ja:
        return f"{base} Emotion cue: {emotion_ja}."
    return base

def _build_spec(functional: str, scene: str, audio_lang: str,
                emotion: Optional[Tuple[str, str]]) -> Dict[str, object]:
    theme = f"{functional} – {scene}"
    pattern_hint = _pattern_for_scene(scene)
    emotion_ja = emotion[0] if emotion else None
    example_stub = emotion[1] if emotion else ""

    spec = {
        "theme": theme,
        "context": _context_for_theme(functional, scene, emotion_ja),
        "count": int(os.getenv("VOCAB_WORDS", "6")),
        "pos": _random_pos_from_env_or_default(),
        "relation_mode": os.getenv("RELATION_MODE", "").strip().lower(),
        "difficulty": _random_difficulty(),
        "pattern_hint": pattern_hint,
        "morphology": _parse_csv_env("MORPHOLOGY"),
        # 演出/学習リワード
        "hook_template": "Shock/Empathy/Time/Release/Status (A/B via HOOK_AB)",
        "visual_hint": f"{scene} scene, emphasize polite tone, micro-dialogue, quick confirm",
        "learner_promise": "After this short, you can say one confident line for this exact situation.",
    }
    # 例文生成に “emotion/例文骨格” をヒントとして渡したいとき
    if example_stub:
        spec["example_stub"] = example_stub  # mainが使わなくても害なし

    return spec

# ─────────────────────────────────────────
# トレンド専用（AUTO_TREND互換）
# ─────────────────────────────────────────
def _trend_pattern_hint(audio_lang: str) -> str:
    common = "roles, positions, equipment, actions, events, venues, rules, scores or times"
    lang = (audio_lang or "").lower()
    if lang == "ja": return "役職・ポジション・道具・動作・イベント名・会場・ルール・得点や時間"
    if lang == "es": return "roles, posiciones, equipo, acciones, eventos, sedes, reglas, puntuaciones y horarios"
    if lang == "fr": return "rôles, postes, équipement, actions, événements, lieux, règles, scores et horaires"
    if lang == "pt": return "funções, posições, equipamentos, ações, eventos, locais, regras, pontuações e horários"
    if lang == "id": return "peran, posisi, peralatan, aksi, acara, tempat, aturan, skor dan waktu"
    if lang == "ko": return "역할, 포지션, 장비, 동작, 이벤트, 장소, 규칙, 점수와 시간"
    return common

def _trend_context(theme: str, audio_lang: str) -> str:
    t = (theme or "").strip() or "the current popular topic"
    return (f"Talk about '{t}' with topic-specific vocabulary: roles/positions, key actions, "
            f"objects/equipment, venues, rules, scores/times. Keep it practical.")

def build_trend_spec(theme: str, audio_lang: str, *, count: Optional[int] = None) -> Dict[str, object]:
    n = int(count or os.getenv("VOCAB_WORDS", "6"))
    level = os.getenv("TREND_DIFFICULTY", "B1").strip().upper()
    if level not in ("A1","A2","B1","B2"):
        level = "B1"
    return {
        "theme": theme,
        "context": _trend_context(theme, audio_lang),
        "count": n,
        "pos": ["noun", "verb", "adjective"],
        "relation_mode": "trend_related",
        "difficulty": level,
        "pattern_hint": _trend_pattern_hint(audio_lang),
        "morphology": [],
        "trend": True,
        "hook_template": "Topic burst → key terms ×3 → quick example",
        "visual_hint": "Bold keyword captions, scoreboard/timer overlay if relevant",
        "learner_promise": "You’ll learn topical words you can use in small talk today.",
    }

# ─────────────────────────────────────────
# 公開API（main.py互換）
# ─────────────────────────────────────────
def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    vocab の場合：
      1) Functional（難易度×言語ペア重み）を選ぶ
      2) その Functional に相性の良い Scene（難易度×言語ペア重み）を選ぶ
      3) sceneに合う “感情トリガー状況” を付与（可能なら）
      4) pattern_hint を scene から自動
    ENV:
      - CEFR_LEVEL=A1/A2/B1/B2
      - FUNCTIONAL_OVERRIDE / SCENE_OVERRIDE
      - ACCOUNT or TARGET_ACCOUNT / L1_OVERRIDE / SUBS
      - RESERVED_FIRST=1（強テーマ1本保証）
      - DETERMINISTIC_DAY=1（日次決定シード）
    """
    ct = (content_type or "vocab").lower()

    # トレンド専用モード
    if ct in ("vocab_trend", "trend"):
        theme_override = os.getenv("THEME_OVERRIDE", "").strip()
        theme = theme_override if theme_override else "popular topic"
        if return_context:
            return build_trend_spec(theme, audio_lang)
        return theme

    # 既定は vocab
    if ct != "vocab":
        # 互換の汎用spec
        if return_context:
            return {
                "theme": "general vocabulary",
                "context": "A simple everyday situation with polite, practical language.",
                "count": int(os.getenv("VOCAB_WORDS", "6")),
                "pos": [],
                "relation_mode": "",
                "difficulty": _random_difficulty(),
                "pattern_hint": _pattern_for_scene(""),
                "morphology": [],
                "hook_template": "Fact → Tip → Example",
                "visual_hint": "Clean captions, single-icon cue",
                "learner_promise": "You’ll get one clear phrase you can reuse today.",
            }
        return "general vocabulary"

    theme_override = os.getenv("THEME_OVERRIDE", "").strip()
    if theme_override and not return_context:
        return theme_override

    l1, tgt = _current_pair(audio_lang)
    reserved = _maybe_reserved(FUNCTIONAL_WEIGHTS_BY_LEVEL.get(_env_level(), {}),
                               SCENES_BASE, l1, tgt)
    if reserved:
        f, s = reserved
        if not return_context:
            return f"{f} – {s}"
        emo = _pick_emotional(s)
        return _build_spec(f, s, audio_lang, emo)

    functional = _pick_functional(audio_lang)
    scene = _pick_scene(functional, audio_lang)
    if not return_context:
        return f"{functional} – {scene}"
    emotion = _pick_emotional(scene)
    return _build_spec(functional, scene, audio_lang, emotion)

# ローカルテスト（任意）
if __name__ == "__main__":
    os.environ.setdefault("ACCOUNT", "acc3")
    os.environ.setdefault("AUDIO_LANG", "en")
    print(pick_by_content_type("vocab", "en"))
    print(json.dumps(pick_by_content_type("vocab", "en", return_context=True), ensure_ascii=False, indent=2))
    print(pick_by_content_type("vocab_trend", "en"))
    print(json.dumps(build_trend_spec("sports finals", "en"), ensure_ascii=False, indent=2))