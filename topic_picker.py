いいですね。実際に修正していきましょう。
現在のコードは下記です。修正したのを全文で出してください。



# topic_picker.py – vocab専用：機能→シーン→パターンを難易度連動の重みでランダム選択
# 追加: トレンド専用 spec を生成する build_trend_spec() / pick_by_content_type(..., content_type="vocab_trend")
import os
import random
from typing import List, Tuple, Dict, Optional

rng = random.SystemRandom()

# ========== 定義 ==========
# 機能（Functional）＝「何をしたいか」の核
FUNCTIONALS: List[str] = [
    "greetings & introductions",
    "numbers & prices",
    "time & dates",
    "asking & giving directions",  # 🧭 道案内（既存を強化）
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
    "job interviews",              # 🎙️ 面接（新規）
]

# シーン（Scene）＝「どこで使うか」
SCENES_BASE: List[str] = [
    "shopping basics",
    "paying & receipts",
    "returns & exchanges",
    "restaurant ordering",
    "dietary needs",
    "transport tickets",
    "airport check-in",
    "security & boarding",
    "hotel check-in/out",
    "facilities & problems",
    "appointments",
    "pharmacy basics",
    "emergencies",
    "delivery and online shopping",
    "phone basics",
    "addresses & contact info",
    "street directions",   # 🧭 道案内（新規）
    "job interview",       # 🎙️ 面接（新規）
]

# Functional → 相性の良い Scene 候補（なければ SCENES_BASE を使う）
SCENES_BY_FUNCTIONAL: Dict[str, List[str]] = {
    "greetings & introductions": ["hotel check-in/out", "small talk at lobby", "phone basics", "restaurant ordering"],
    "numbers & prices": ["shopping basics", "paying & receipts", "transport tickets"],
    "time & dates": ["appointments", "transport tickets", "restaurant ordering"],
    "asking & giving directions": ["street directions", "transport tickets", "airport check-in", "hotel check-in/out"],
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
    "job interviews": ["job interview", "appointments", "phone basics"],  # 追加
}

# テーマ文脈（英語）…モデルへの指示用（出力言語とは別）
def _context_for_theme(functional: str, scene: str) -> str:
    f = (functional or "").lower()
    s = (scene or "").lower()

    # scene 優先の短文脈
    if "job interview" in s or "interview" in s:
        return "A candidate answers simple job interview questions clearly and politely."
    if "street directions" in s or "direction" in s:
        return "A person asks for directions and confirms a simple route."
    if "hotel" in s:
        return "A guest talks to the hotel front desk about a simple request."
    if "restaurant" in s:
        return "A customer orders food and asks a brief question politely."
    if "shopping" in s:
        return "A customer asks for items and prices in a store."
    if "paying" in s or "receipt" in s:
        return "A customer pays and asks for a receipt at the counter."
    if "return" in s or "exchange" in s:
        return "A customer politely asks to return or exchange an item."
    if "airport" in s or "boarding" in s or "security" in s:
        return "A traveler checks in at the airport and asks a simple question."
    if "transport" in s or "ticket" in s:
        return "A traveler buys a ticket and checks a simple detail."
    if "facility" in s or "problem" in s:
        return "A guest reports a small problem and asks for help."
    if "appointment" in s:
        return "A person makes or confirms a simple appointment time."
    if "pharmacy" in s:
        return "A customer asks for basic medicine politely."
    if "emergenc" in s:
        return "A person quickly explains a simple urgent situation."
    if "delivery" in s or "online" in s:
        return "A customer checks delivery status or address details."
    if "phone" in s:
        return "A caller asks a simple question on the phone."
    if "address" in s or "contact" in s:
        return "Two people exchange addresses or contact information."

    # functional による汎用 fallback
    if "interview" in f:
        return "A candidate introduces themselves and answers simple interview questions."
    if "greeting" in f or "introductions" in f:
        return "Two people meet for the first time and introduce themselves."
    if "number" in f or "price" in f:
        return "A buyer asks the price and understands simple numbers."
    if "time" in f or "date" in f:
        return "People check the time or set a simple date."
    if "direction" in f:
        return "Someone asks how to get to a nearby place."
    if "polite request" in f:
        return "Someone politely asks for a small favor or item."
    if "offer" in f or "suggestion" in f:
        return "A person makes a friendly suggestion."
    if "clarifying" in f or "confirm" in f:
        return "People clarify a small detail to avoid confusion."
    if "problem" in f:
        return "Someone explains a small issue and asks for help."
    if "apolog" in f:
        return "Someone says sorry briefly for a small mistake."
    if "agree" in f or "disagree" in f:
        return "People show simple agreement or polite disagreement."
    if "preference" in f or "opinion" in f:
        return "Someone says what they like or prefer."
    if "making plan" in f:
        return "Two friends plan a simple meetup."
    if "past" in f:
        return "Someone shares a short past experience."
    if "future" in f:
        return "People schedule something in the near future."
    if "comparison" in f:
        return "A person compares two options briefly."
    if "frequency" in f or "habit" in f:
        return "Someone talks about how often they do something."
    if "permission" in f or "ability" in f:
        return "A person asks for permission or says they can or cannot."
    if "cause" in f or "reason" in f:
        return "Someone gives a short reason for something."
    if "condition" in f or "advice" in f:
        return "A person gives a simple if-advice."
    if "small talk" in f:
        return "Two people start light small talk."
    return "A simple everyday situation with polite, practical language."

# pattern 候補（学習向けの再利用性重視）
PATTERN_CANDIDATES: List[str] = [
    "polite_request",
    "ask_permission",
    "ask_availability",
    "confirm_detail",
    "make_suggestion",
    "give_advice",
    "express_opinion",
    "express_consequence",
    "ask_direction",     # 道案内向け
    "confirm_route",     # 道案内向け
    "self_introduction", # 面接・自己紹介
    "talk_experience",   # 面接・過去経験
    "",
]

# Functional/Scene → pattern の重み（学習需要＋自然さ）
PATTERN_WEIGHTS_BY_FUNCTIONAL: Dict[str, Dict[str, int]] = {
    "polite requests": {
        "polite_request": 6, "ask_permission": 4, "confirm_detail": 3, "make_suggestion": 2
    },
    "asking & giving directions": {
        "ask_direction": 6, "confirm_route": 4, "confirm_detail": 3, "polite_request": 2
    },
    "making plans": {
        "make_suggestion": 6, "ask_availability": 3, "confirm_detail": 3, "express_consequence": 2
    },
    "describing problems": {
        "confirm_detail": 5, "polite_request": 3, "give_advice": 3, "express_consequence": 2
    },
    "job interviews": {
        "self_introduction": 6, "talk_experience": 5, "express_opinion": 3, "confirm_detail": 2
    },
    # Scene 名でもヒットさせる（マージ用）
    "street directions": {
        "ask_direction": 6, "confirm_route": 4, "confirm_detail": 2
    },
    "job interview": {
        "self_introduction": 6, "talk_experience": 5, "express_opinion": 3
    },
    "returns & exchanges": {
        "confirm_detail": 5, "polite_request": 4, "express_consequence": 2
    },
}

# 難易度ごとの functional・scene の重み（相対値）
# A1/A2 は基礎機能・基礎シーンを厚め、B1/B2 は問題解決・議論系や面接を厚め
FUNCTIONAL_WEIGHTS_BY_LEVEL: Dict[str, Dict[str, int]] = {
    "A1": {
        "greetings & introductions": 8, "numbers & prices": 7, "time & dates": 6,
        "polite requests": 5, "asking & giving directions": 6,
        "making plans": 4, "preferences & opinions": 3, "small talk starters": 3,
    },
    "A2": {
        "greetings & introductions": 6, "numbers & prices": 5, "time & dates": 5,
        "polite requests": 6, "asking & giving directions": 6,
        "making plans": 5, "clarifying & confirming": 4,
        "preferences & opinions": 4, "small talk starters": 4,
        "describing problems": 3, "permission & ability": 3,
    },
    "B1": {
        "clarifying & confirming": 6, "describing problems": 6,
        "condition & advice": 5, "cause & reason": 5,
        "agreeing & disagreeing": 4, "comparisons": 4,
        "past experiences": 3, "future arrangements": 3,
        "polite requests": 3, "making plans": 3, "job interviews": 5,
    },
    "B2": {
        "agreeing & disagreeing": 6, "preferences & opinions": 6,
        "cause & reason": 5, "condition & advice": 5,
        "comparisons": 4, "clarifying & confirming": 4,
        "describing problems": 4, "job interviews": 6,
    },
}

SCENE_WEIGHTS_BY_LEVEL: Dict[str, Dict[str, int]] = {
    "A1": {
        "shopping basics": 8, "restaurant ordering": 7, "paying & receipts": 6,
        "phone basics": 5, "addresses & contact info": 5, "transport tickets": 5,
        "hotel check-in/out": 4, "street directions": 6,
    },
    "A2": {
        "restaurant ordering": 7, "shopping basics": 6, "paying & receipts": 6,
        "appointments": 5, "transport tickets": 5, "hotel check-in/out": 5,
        "facilities & problems": 4, "pharmacy basics": 4, "street directions": 6,
    },
    "B1": {
        "facilities & problems": 6, "returns & exchanges": 6,
        "appointments": 5, "security & boarding": 5,
        "delivery and online shopping": 4, "pharmacy basics": 4,
        "job interview": 5,
    },
    "B2": {
        "emergencies": 6, "security & boarding": 5,
        "returns & exchanges": 5, "facilities & problems": 5,
        "delivery and online shopping": 4, "job interview": 6,
    },
}

# ========== ユーティリティ ==========
def _env_level() -> str:
    v = os.getenv("CEFR_LEVEL", "").strip().upper()
    return v if v in ("A1", "A2", "B1", "B2") else "A2"

def _choose_weighted(items: List[Tuple[str, int]]) -> str:
    pool, weights = zip(*[(k, max(0, w)) for k, w in items if w > 0])
    return rng.choices(pool, weights=weights, k=1)[0]

def _weights_from_dict(keys: List[str], table: Dict[str, int]) -> List[Tuple[str, int]]:
    return [(k, table.get(k, 1)) for k in keys]

def _pick_functional() -> str:
    override = os.getenv("FUNCTIONAL_OVERRIDE", "").strip()
    if override:
        return override
    level = _env_level()
    weights = FUNCTIONAL_WEIGHTS_BY_LEVEL.get(level, {})
    items = _weights_from_dict(FUNCTIONALS, weights)
    return _choose_weighted(items)

def _pick_scene(functional: str) -> str:
    override = os.getenv("SCENE_OVERRIDE", "").strip()
    if override:
        return override
    level = _env_level()
    base = SCENES_BY_FUNCTIONAL.get(functional, SCENES_BASE)
    # level 重みを適用（未定義は1）
    level_weights = SCENE_WEIGHTS_BY_LEVEL.get(level, {})
    items = _weights_from_dict(base, level_weights)
    if not any(w > 1 for _, w in items):
        items = [(s, 2) for s in base]  # 均等だが少し厚め
    return _choose_weighted(items)

def _pick_pattern(functional: str, scene: str) -> str:
    override = os.getenv("PATTERN_HINT", "").strip()
    if override:
        return override

    # functional / scene の重みをマージ
    merged: Dict[str, int] = {k: 1 for k in PATTERN_CANDIDATES}
    for k, w in PATTERN_WEIGHTS_BY_FUNCTIONAL.get(functional, {}).items():
        merged[k] = merged.get(k, 1) + w
    for k, w in PATTERN_WEIGHTS_BY_FUNCTIONAL.get(scene, {}).items():
        merged[k] = merged.get(k, 1) + w

    # level バイアス（A1/A2 は polite/confirm/directions、B1/B2 は interview/opinion/logic）
    level = _env_level()
    level_bias: Dict[str, Dict[str, int]] = {
        "A1": {"polite_request": 3, "ask_permission": 2, "confirm_detail": 2, "ask_direction": 3, "confirm_route": 2},
        "A2": {"polite_request": 2, "confirm_detail": 2, "ask_availability": 2, "ask_direction": 3, "confirm_route": 2},
        "B1": {"give_advice": 3, "make_suggestion": 2, "express_opinion": 2, "self_introduction": 2, "talk_experience": 2},
        "B2": {"express_opinion": 3, "express_consequence": 2, "give_advice": 2, "self_introduction": 2, "talk_experience": 3},
    }
    for k, w in level_bias.get(level, {}).items():
        merged[k] = merged.get(k, 1) + w

    items = [(k, merged.get(k, 1)) for k in PATTERN_CANDIDATES]
    return _choose_weighted(items)

def _random_pos_from_env_or_default() -> List[str]:
    v = os.getenv("VOCAB_POS", "").strip()
    if v:
        return [x.strip() for x in v.split(",") if x.strip()]
    # POS は main.py 側で言語別に最終決定してもOK。ここでは未指定 or ランダム軽量にしておく
    return []

def _random_difficulty() -> str:
    env = os.getenv("CEFR_LEVEL", "").strip().upper()
    if env in ("A1", "A2", "B1", "B2"):
        return env
    return rng.choice(["A2", "B1", "B2"])

def _parse_csv_env(name: str) -> List[str]:
    v = os.getenv(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]

def _build_spec(functional: str, scene: str, audio_lang: str) -> Dict[str, object]:
    theme = f"{functional} – {scene}"
    spec = {
        "theme": theme,
        "context": _context_for_theme(functional, scene),
        "count": int(os.getenv("VOCAB_WORDS", "6")),
        "pos": _random_pos_from_env_or_default(),                 # POS は ENV 優先（未指定なら main.py へ委譲）
        "relation_mode": os.getenv("RELATION_MODE", "").strip().lower(),
        "difficulty": _random_difficulty(),
        "pattern_hint": _pick_pattern(functional, scene),
        "morphology": _parse_csv_env("MORPHOLOGY"),
    }
    return spec

# ========== トレンド専用: 関連語を“強く”引かせる spec ==========
def _trend_pattern_hint(audio_lang: str) -> str:
    """
    topic に固有の “役職/ポジション/機材/動作/イベント/会場/ルール/スコア・時間”
    といった『話題に特化した語』を優先させるための軽い誘導語。
    """
    common = "roles, positions, equipment, actions, events, venues, rules, scores or times"
    lang = (audio_lang or "").lower()
    if lang == "ja":
        return "役職・ポジション・道具・動作・イベント名・会場・ルール・得点や時間"
    if lang == "es":
        return "roles, posiciones, equipo, acciones, eventos, sedes, reglas, puntuaciones y horarios"
    if lang == "fr":
        return "rôles, postes, équipement, actions, événements, lieux, règles, scores et horaires"
    if lang == "pt":
        return "funções, posições, equipamentos, ações, eventos, locais, regras, pontuações e horários"
    if lang == "id":
        return "peran, posisi, peralatan, aksi, acara, tempat, aturan, skor dan waktu"
    if lang == "ko":
        return "역할, 포지션, 장비, 동작, 이벤트, 장소, 규칙, 점수와 시간"
    return common

def _trend_context(theme: str, audio_lang: str) -> str:
    """
    例文生成にも効きやすい短い英語文脈（生成モデルへの指示用）。
    出力言語は main.py 側で制御するため、ここは英語ベースでOK。
    """
    t = (theme or "").strip()
    if not t:
        t = "the current popular topic"
    return (
        f"Talk about '{t}' with topic-specific vocabulary: roles/positions, key actions, objects/equipment, "
        f"venues/stadiums, rules, scores/times. Keep it practical."
    )

def build_trend_spec(theme: str, audio_lang: str, *, count: Optional[int] = None) -> Dict[str, object]:
    """
    トレンド話題に“関連する用語”を多めに引くための spec を生成。
    - relation_mode: 'trend_related'（main.py 側の _gen_vocab_list_from_spec が解釈）
    - pos: noun/verb/adjective を優先（品詞が偏らないように）
    - difficulty: TREND_DIFFICULTY（未設定なら B1）
    - pattern_hint: 言語別の誘導語（役職/動作/道具/会場など）
    """
    n = int(count or os.getenv("VOCAB_WORDS", "6"))
    level = os.getenv("TREND_DIFFICULTY", "B1").strip().upper()
    if level not in ("A1", "A2", "B1", "B2"):
        level = "B1"
    spec: Dict[str, object] = {
        "theme": theme,
        "context": _trend_context(theme, audio_lang),
        "count": n,
        "pos": ["noun", "verb", "adjective"],
        "relation_mode": "trend_related",     # ★ ここが肝
        "difficulty": level,
        "pattern_hint": _trend_pattern_hint(audio_lang),
        "morphology": [],                     # 必要なら ENV で main と同様に拡張可
        "trend": True,
    }
    return spec

# ========== 外部API ==========
def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    vocab の場合：
      1) Functional を難易度連動の重みで選ぶ
      2) その Functional に相性の良い Scene を重みで選ぶ（難易度も反映）
      3) pattern_hint も上記に連動して重み選択
    ENV:
      - CEFR_LEVEL=A1/A2/B1/B2 で難易度固定
      - FUNCTIONAL_OVERRIDE / SCENE_OVERRIDE / PATTERN_HINT で強制上書き
      - THEME_OVERRIDE: theme 文字列を丸ごと上書き（return_context=False の互換用途）

    追加:
      - content_type="vocab_trend" または "trend" のとき:
        THEME_OVERRIDE があればそれをテーマとして build_trend_spec を返す（return_context=True 推奨）。
        return_context=False の場合はテーマ文字列のみ返す。
    戻り値:
      - return_context=False → "functional – scene" もしくは THEME（trend時）
      - return_context=True  → dict(spec)
    """
    ct = (content_type or "vocab").lower()

    # ---- トレンド専用モード ----
    if ct in ("vocab_trend", "trend"):
        theme_override = os.getenv("THEME_OVERRIDE", "").strip()
        theme = theme_override if theme_override else "popular topic"
        if return_context:
            return build_trend_spec(theme, audio_lang)
        return theme

    # ---- 既存の vocab モード ----
    if ct != "vocab":
        if return_context:
            return {
                "theme": "general vocabulary",
                "context": "A simple everyday situation with polite, practical language.",
                "count": int(os.getenv("VOCAB_WORDS", "6")),
                "pos": [],
                "relation_mode": "",
                "difficulty": _random_difficulty(),
                "pattern_hint": "",
                "morphology": [],
            }
        return "general vocabulary"

    theme_override = os.getenv("THEME_OVERRIDE", "").strip()
    if theme_override and not return_context:
        return theme_override

    functional = _pick_functional()
    scene = _pick_scene(functional)

    if not return_context:
        return f"{functional} – {scene}"

    return _build_spec(functional, scene, audio_lang)

# ローカルテスト
if __name__ == "__main__":
    print(pick_by_content_type("vocab", "en"))
    print(pick_by_content_type("vocab", "en", return_context=True))
    print(pick_by_content_type("vocab_trend", "en"))
    print(pick_by_content_type("vocab_trend", "en", return_context=True))
