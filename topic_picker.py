# topic_picker.py – vocab専用：学習語彙に最適化（Functional中心＋Sceneは文脈専用）
# 方針：
#   - 単語選定は「学習カテゴリ（Functional）」中心
#   - Scene は例文文脈 context にのみ使う（語彙テーマには含めない）
#   - 難易度・重み付け・トレンド対応・環境変数は維持
#   - pos は Functional に応じた既定を付与（main.py 側の ENV で上書き可能）

import os, random
from typing import List, Tuple, Dict, Optional

rng = random.SystemRandom()

# =========================
# 学習カテゴリ（Functional）
# =========================
# 物体名詞に偏らず、動詞・形容詞・接続表現・コロケーションを引きやすい構成
FUNCTIONALS: List[str] = [
    "daily conversation basics",
    "useful verbs for communication",
    "expressing opinions & feelings",
    "requests & suggestions",
    "cause & effect expressions",
    "connectors & transition words",
    "time & frequency expressions",
    "quantity & degree expressions",
    "functional vocabulary for place & movement",
    "work & service interaction basics",
    "common adjectives for people & things",
    "useful collocations & set phrases",
    "essential prepositions & particles",
]

# シーン（例文用の文脈ヒントとしてのみ使用）
SCENES: List[str] = [
    "at the hotel front desk",
    "at a restaurant",
    "during a phone call",
    "at school",
    "in an office",
    "on a trip",
    "shopping",
    "asking for help",
    "making an appointment",
    "in a meeting",
    "talking to friends",
]

# =========================
# Functional ごとの既定 POS バイアス
# （main.py が spec['pos'] を参照。ENV VOCAB_POS があれば main.py 側が優先する）
# =========================
DEFAULT_POS_BY_FUNCTIONAL: Dict[str, List[str]] = {
    "daily conversation basics":                  ["verb", "adjective", "noun"],
    "useful verbs for communication":             ["verb"],
    "expressing opinions & feelings":             ["verb", "adjective", "adverb"],
    "requests & suggestions":                     ["verb", "modal"],
    "cause & effect expressions":                 ["conjunction", "adverb", "verb"],
    "connectors & transition words":              ["conjunction", "adverb"],
    "time & frequency expressions":               ["adverb", "noun"],
    "quantity & degree expressions":              ["adverb", "adjective"],
    "functional vocabulary for place & movement": ["verb", "preposition", "adverb"],
    "work & service interaction basics":          ["verb", "noun", "adjective"],
    "common adjectives for people & things":      ["adjective", "adverb"],
    "useful collocations & set phrases":          ["verb", "noun", "adjective"],
    "essential prepositions & particles":         ["preposition", "conjunction"],
}

# =========================
# 難易度別 Functional の重み
# =========================
FUNCTIONAL_WEIGHTS_BY_LEVEL: Dict[str, Dict[str, int]] = {
    "A1": {
        "daily conversation basics": 8,
        "useful verbs for communication": 7,
        "common adjectives for people & things": 6,
        "time & frequency expressions": 5,
        "requests & suggestions": 4,
        "connectors & transition words": 3,
    },
    "A2": {
        "daily conversation basics": 6,
        "useful verbs for communication": 6,
        "requests & suggestions": 6,
        "time & frequency expressions": 5,
        "quantity & degree expressions": 4,
        "connectors & transition words": 4,
        "functional vocabulary for place & movement": 4,
    },
    "B1": {
        "requests & suggestions": 6,
        "expressing opinions & feelings": 6,
        "cause & effect expressions": 6,
        "connectors & transition words": 5,
        "work & service interaction basics": 5,
        "useful collocations & set phrases": 4,
    },
    "B2": {
        "expressing opinions & feelings": 6,
        "cause & effect expressions": 6,
        "connectors & transition words": 5,
        "work & service interaction basics": 5,
        "useful collocations & set phrases": 4,
        "essential prepositions & particles": 4,
    },
}

# =========================
# 難易度・語数制御
# =========================
DIFF_MODE = os.getenv("DIFF_MODE", "weighted").strip().lower()
DIFF_WEIGHTS_ENV = os.getenv("DIFF_WEIGHTS", "A1:1,A2:2,B1:3,B2:2").strip()
WORDS_BY_DIFF_ENV = os.getenv("WORDS_BY_DIFF", "A1:8,A2:8,B1:6,B2:6").strip()

def _parse_weights_env(s: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for part in (s or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().upper()
            try:
                out[k] = max(0, int(v.strip()))
            except Exception:
                pass
    # デフォ補完（無指定時の安全値）
    for k, v in {"A1":1, "A2":2, "B1":3, "B2":2}.items():
        out.setdefault(k, v)
    return out

def _parse_words_env(s: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for part in (s or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().upper()
            try:
                out[k] = max(1, int(v.strip()))
            except Exception:
                pass
    return out

DIFF_WEIGHTS = _parse_weights_env(DIFF_WEIGHTS_ENV)
WORDS_BY_DIFF = _parse_words_env(WORDS_BY_DIFF_ENV)

def _pick_difficulty() -> str:
    env = os.getenv("CEFR_LEVEL", "").strip().upper()
    if env in ("A1", "A2", "B1", "B2"):
        return env
    if DIFF_MODE == "fixed":
        return "B1"
    if DIFF_MODE == "random":
        return rng.choice(["A1", "A2", "B1", "B2"])
    # weighted
    pool, weights = zip(*[(k, DIFF_WEIGHTS.get(k, 1)) for k in ("A1","A2","B1","B2")])
    return rng.choices(pool, weights=weights, k=1)[0]

def _count_for_diff(diff: str) -> int:
    env_count = os.getenv("VOCAB_WORDS", "").strip()
    if env_count.isdigit():
        return max(1, int(env_count))
    return WORDS_BY_DIFF.get(diff, 8 if diff in ("A1","A2") else 6)

# =========================
# Weighted Random Utility
# =========================
def _env_level() -> str:
    v = os.getenv("CEFR_LEVEL", "").strip().upper()
    return v if v in ("A1","A2","B1","B2") else "A2"

def _choose_weighted(items: List[Tuple[str,int]]) -> str:
    pool, weights = zip(*[(k,w) for k,w in items if w>0])
    return rng.choices(pool, weights=weights, k=1)[0]

# =========================
# Functional / Scene 選択
# =========================
def _pick_functional() -> str:
    override = os.getenv("FUNCTIONAL_OVERRIDE", "").strip()
    if override:
        return override
    level = _env_level()
    weights = FUNCTIONAL_WEIGHTS_BY_LEVEL.get(level, {})
    # 定義外は重み1で残す（将来の追加に安全）
    items = [(f, max(1, int(weights.get(f, 1)))) for f in FUNCTIONALS]
    return _choose_weighted(items)

def _pick_scene() -> str:
    override = os.getenv("SCENE_OVERRIDE", "").strip()
    if override:
        return override
    return rng.choice(SCENES)

def _default_pos_for(functional: str) -> List[str]:
    return DEFAULT_POS_BY_FUNCTIONAL.get(functional, [])

# =========================
# Context（例文文脈）
# =========================
def _context_for_scene(scene: str) -> str:
    s = (scene or "").lower()
    if "hotel" in s:       return "A guest speaks politely with hotel staff."
    if "restaurant" in s:  return "A customer orders food or asks a question politely."
    if "phone" in s:       return "A person speaks on the phone for a simple matter."
    if "office" in s:      return "An employee talks with a coworker in an office."
    if "school" in s:      return "A student speaks with a teacher or classmate."
    if "shopping" in s:    return "A customer asks for prices or products at a store."
    if "help" in s:        return "Someone asks for help politely."
    if "trip" in s:        return "A traveler asks for directions or information."
    if "appointment" in s: return "A person schedules or confirms a meeting."
    if "meeting" in s:     return "Colleagues discuss a simple agenda item."
    if "friends" in s:     return "Two friends chat casually in everyday language."
    return "A simple everyday situation with practical, polite language."

# =========================
# Spec構築
# =========================
def _build_spec(functional: str, scene: str, audio_lang: str) -> Dict[str,object]:
    difficulty = _pick_difficulty()
    count = _count_for_diff(difficulty)

    # pos は Functional に応じた既定を付与（ENV VOCAB_POS があれば main.py で上書き可能）
    pos_default = _default_pos_for(functional)

    spec: Dict[str, object] = {
        # === main.py 互換キー ===
        "theme": functional,                         # 学習カテゴリのみ（タイトル用途）
        "context": _context_for_scene(scene),        # Sceneは例文context用のみ
        "count": count,
        "pos": pos_default,                          # 既定POS（名詞過多を避ける）
        "relation_mode": "functional_family",
        "difficulty": difficulty,
        "pattern_hint": "",                          # main.py 側が自動推定/未使用でも無害
        "morphology": [],

        # === 追加情報（無害） ===
        "functional": functional,
        "scene": scene,
        "role_from": "person A",
        "role_to": "person B",
        "family": "learning_core",
    }
    return spec

# =========================
# Trend用Spec
# =========================
def build_trend_spec(theme: str, audio_lang: str, *, count: Optional[int] = None) -> Dict[str,object]:
    n = int(count or os.getenv("VOCAB_WORDS", "6"))
    level = os.getenv("TREND_DIFFICULTY","B1").strip().upper()
    if level not in ("A1","A2","B1","B2"):
        level = "B1"
    return {
        "theme": theme or "popular topic",
        "context": "Talk about current popular themes using everyday, reusable vocabulary.",
        "count": n,
        "pos": ["noun","verb","adjective"],
        "relation_mode": "trend_related",
        "difficulty": level,
        "pattern_hint": "roles, actions, equipment, events, places",
        "morphology": [],
        "trend": True,
        "functional": "trend",
        "scene": "general news talk",
        "role_from": "person A",
        "role_to": "person B",
        "family": "trend_related",
    }

# =========================
# メイン関数
# =========================
def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    戻り値:
      - return_context=False → theme 文字列（= functional 名。Sceneは含めない）
      - return_context=True  → dict(spec)（context に Scene 由来の文脈を付与）
    """
    ct = (content_type or "vocab").lower()

    # ---- トレンド専用 ----
    if ct in ("vocab_trend", "trend"):
        theme_override = os.getenv("THEME_OVERRIDE", "").strip()
        theme = theme_override or "popular topic"
        if return_context:
            return build_trend_spec(theme, audio_lang)
        return theme

    # ---- 既定（vocab）以外のフォールバック ----
    if ct != "vocab":
        diff = _pick_difficulty()
        if return_context:
            return {
                "theme": "general vocabulary",
                "context": "A simple everyday situation with polite, practical language.",
                "count": _count_for_diff(diff),
                "pos": [],
                "relation_mode": "",
                "difficulty": diff,
                "pattern_hint": "",
                "morphology": [],
            }
        return "general vocabulary"

    # ---- vocab モード ----
    functional = _pick_functional()
    scene = _pick_scene()

    if not return_context:
        # タイトル用は Functional のみ返す（“旅行必需品”のような物体名詞系を避ける）
        return functional
    return _build_spec(functional, scene, audio_lang)

# =========================
# ローカルテスト
# =========================
if __name__ == "__main__":
    print("— vocab (string) —")
    print(pick_by_content_type("vocab", "en"))
    print("— vocab (spec) —")
    print(pick_by_content_type("vocab", "en", return_context=True))
    print("— trend (spec) —")
    print(pick_by_content_type("vocab_trend", "en", return_context=True))