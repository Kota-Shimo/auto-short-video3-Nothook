# topic_picker.py – vocab専用：学習語彙に最適化（Functional中心＋Sceneは文脈専用）
# 方針：
#   - 単語選定は「学習カテゴリ（Functional）」中心
#   - Scene は例文文脈 context にのみ使う（語彙テーマには含めない）
#   - 難易度・重み付け・パターンは既存 main.py と互換
#   - CEFR / 環境変数 / トレンドモード対応は維持

import os, random
from typing import List, Tuple, Dict, Optional

rng = random.SystemRandom()

# =========================
# 学習カテゴリ（Functional）
# =========================
FUNCTIONALS: List[str] = [
    "daily actions",
    "feelings and emotions",
    "requests and offers",
    "permissions and prohibitions",
    "reasons and results",
    "time and frequency",
    "quantity and degree",
    "connections and transitions",
    "travel essentials",
    "workplace basics",
    "describing people and things",
    "common verbs",
    "common adjectives",
    "utility and connectors",
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

# 難易度別 Functional の重み
FUNCTIONAL_WEIGHTS_BY_LEVEL: Dict[str, Dict[str, int]] = {
    "A1": {
        "daily actions": 7, "feelings and emotions": 6,
        "time and frequency": 5, "common verbs": 7,
        "common adjectives": 6, "requests and offers": 4,
    },
    "A2": {
        "daily actions": 6, "feelings and emotions": 6,
        "requests and offers": 6, "permissions and prohibitions": 5,
        "time and frequency": 5, "connections and transitions": 4,
        "travel essentials": 4, "quantity and degree": 4,
    },
    "B1": {
        "requests and offers": 6, "permissions and prohibitions": 5,
        "reasons and results": 6, "connections and transitions": 5,
        "workplace basics": 5, "utility and connectors": 4,
    },
    "B2": {
        "reasons and results": 5, "connections and transitions": 5,
        "workplace basics": 5, "utility and connectors": 5,
        "describing people and things": 4,
    },
}

# =========================
# 難易度・語数制御
# =========================
DIFF_MODE = os.getenv("DIFF_MODE", "weighted").strip().lower()
DIFF_WEIGHTS_ENV = os.getenv("DIFF_WEIGHTS", "A1:1,A2:2,B1:3,B2:2").strip()
WORDS_BY_DIFF_ENV = os.getenv("WORDS_BY_DIFF", "A1:8,A2:8,B1:6,B2:6").strip()

def _parse_weights_env(s: str) -> Dict[str, int]:
    out = {}
    for part in s.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().upper()] = int(v.strip())
    return out

def _parse_words_env(s: str) -> Dict[str, int]:
    out = {}
    for part in s.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().upper()] = int(v.strip())
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
    pool, weights = zip(*[(k, DIFF_WEIGHTS.get(k, 1)) for k in ("A1","A2","B1","B2")])
    return rng.choices(pool, weights=weights, k=1)[0]

def _count_for_diff(diff: str) -> int:
    env_count = os.getenv("VOCAB_WORDS", "").strip()
    if env_count.isdigit():
        return int(env_count)
    return WORDS_BY_DIFF.get(diff, 8 if diff in ("A1", "A2") else 6)

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
    if override: return override
    level = _env_level()
    weights = FUNCTIONAL_WEIGHTS_BY_LEVEL.get(level, {})
    items = [(f, weights.get(f, 1)) for f in FUNCTIONALS]
    return _choose_weighted(items)

def _pick_scene() -> str:
    override = os.getenv("SCENE_OVERRIDE", "").strip()
    if override: return override
    return rng.choice(SCENES)

# =========================
# Context（例文文脈）
# =========================
def _context_for_scene(scene: str) -> str:
    s = scene.lower()
    if "hotel" in s: return "A guest speaks politely with hotel staff."
    if "restaurant" in s: return "A customer orders food or asks a question politely."
    if "phone" in s: return "A person speaks on the phone for a simple matter."
    if "office" in s: return "An employee talks with a coworker in an office."
    if "school" in s: return "A student speaks with a teacher or classmate."
    if "shopping" in s: return "A customer asks for prices or products at a store."
    if "help" in s: return "Someone asks for help politely."
    if "trip" in s: return "A traveler asks for directions or information."
    if "appointment" in s: return "A person schedules or confirms a meeting."
    return "A simple everyday situation with practical, polite language."

# =========================
# Spec構築
# =========================
def _build_spec(functional: str, scene: str, audio_lang: str) -> Dict[str,object]:
    difficulty = _pick_difficulty()
    count = _count_for_diff(difficulty)
    spec = {
        "theme": functional,                         # 学習カテゴリのみ
        "context": _context_for_scene(scene),         # Sceneは例文context用のみ
        "count": count,
        "pos": [],                                   # POSはmain.py側で制御
        "relation_mode": "functional_family",
        "difficulty": difficulty,
        "pattern_hint": "",                          # main.pyが自動推定
        "morphology": [],
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
    return {
        "theme": theme or "popular topic",
        "context": "Talk about current popular themes and related vocabulary.",
        "count": n,
        "pos": ["noun","verb","adjective"],
        "relation_mode": "trend_related",
        "difficulty": os.getenv("TREND_DIFFICULTY","B1"),
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
    ct = (content_type or "vocab").lower()

    if ct in ("vocab_trend", "trend"):
        theme_override = os.getenv("THEME_OVERRIDE", "").strip()
        theme = theme_override or "popular topic"
        if return_context:
            return build_trend_spec(theme, audio_lang)
        return theme

    if ct != "vocab":
        if return_context:
            diff = _pick_difficulty()
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

    # Functional & Scene 選択
    functional = _pick_functional()
    scene = _pick_scene()

    if not return_context:
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