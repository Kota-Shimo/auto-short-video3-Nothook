# topic_picker.py – vocab専用：機能→シーン→パターンを難易度連動の重みでランダム選択
# 方針: 「job interview」は Scene 専用に統一（Functional から除外）
# 追加:
#  - 役割（role_from / role_to）をシーンに整合する形で付与
#  - 機能ごとの既定POSバイアス / 既定relation_mode / 既定patternの強化
#  - validate_spec() で 機能↔シーン↔パターン↔役割 の整合性チェック（破壊的変更なし：未知キーは main.py 側が無視しても安全）
#  - トレンド専用 spec を生成する build_trend_spec() / pick_by_content_type(..., content_type="vocab_trend")
#  - ★ 追加修正（最小限）：難易度の重み付きランダム（DIFF_MODE/DIFF_WEIGHTS）と難易度別語数（WORDS_BY_DIFF）
import os
import random
from typing import List, Tuple, Dict, Optional

rng = random.SystemRandom()

# =========================
# 定義（固定候補カタログ）
# =========================

# 機能（Functional）＝「何をしたいか」の核（※面接は除外し、言語機能に純化）
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
    # （面接系は下の Scene 側に集約）
]

# シーン（Scene）＝「どこで使うか」※ job interview をこちらに一本化
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
    "street directions",
    "job interview",               # ← Scene 専用
    "small talk at lobby",
    "making plans in lobby",
]

# Functional → 相性の良い Scene 候補（なければ SCENES_BASE を使う）
SCENES_BY_FUNCTIONAL: Dict[str, List[str]] = {
    "greetings & introductions": ["hotel check-in/out", "small talk at lobby", "phone basics", "restaurant ordering", "job interview"],
    "numbers & prices": ["shopping basics", "paying & receipts", "transport tickets"],
    "time & dates": ["appointments", "transport tickets", "restaurant ordering", "job interview"],
    "asking & giving directions": ["street directions", "transport tickets", "airport check-in", "hotel check-in/out"],
    "polite requests": ["restaurant ordering", "hotel check-in/out", "facilities & problems", "job interview"],
    "offers & suggestions": ["restaurant ordering", "making plans in lobby", "phone basics"],
    "clarifying & confirming": ["paying & receipts", "appointments", "security & boarding", "job interview"],
    "describing problems": ["facilities & problems", "pharmacy basics", "returns & exchanges"],
    "apologizing & excuses": ["appointments", "restaurant ordering", "transport tickets"],
    "agreeing & disagreeing": ["making plans in lobby", "restaurant ordering", "job interview"],
    "preferences & opinions": ["restaurant ordering", "shopping basics", "job interview"],
    "making plans": ["appointments", "restaurant ordering", "phone basics", "making plans in lobby"],
    "past experiences": ["small talk at lobby", "restaurant ordering", "job interview"],
    "future arrangements": ["appointments", "transport tickets", "job interview"],
    "comparisons": ["shopping basics", "restaurant ordering"],
    "frequency & habits": ["small talk at lobby", "pharmacy basics"],
    "permission & ability": ["security & boarding", "hotel check-in/out"],
    "cause & reason": ["returns & exchanges", "facilities & problems", "job interview"],
    "condition & advice": ["pharmacy basics", "emergencies", "dietary needs"],
    "small talk starters": ["small talk at lobby", "restaurant ordering", "phone basics"],
}

# シーンごとの自然な役割ペア（視点）
ROLE_PAIRS_BY_SCENE: Dict[str, List[Tuple[str, str]]] = {
    "hotel check-in/out": [("front-desk clerk", "guest"), ("guest", "front-desk clerk")],
    "restaurant ordering": [("server", "guest"), ("guest", "server")],
    "street directions": [("local", "tourist"), ("tourist", "local")],
    "shopping basics": [("shop staff", "customer"), ("customer", "shop staff")],
    "paying & receipts": [("cashier", "customer"), ("customer", "cashier")],
    "returns & exchanges": [("shop staff", "customer"), ("customer", "shop staff")],
    "appointments": [("staff", "customer"), ("customer", "staff")],
    "pharmacy basics": [("pharmacist", "customer"), ("customer", "pharmacist")],
    "security & boarding": [("staff", "traveler"), ("traveler", "staff")],
    "transport tickets": [("ticket clerk", "traveler"), ("traveler", "ticket clerk")],
    "airport check-in": [("agent", "traveler"), ("traveler", "agent")],
    "facilities & problems": [("staff", "guest"), ("guest", "staff")],
    "dietary needs": [("server", "guest"), ("guest", "server")],
    "phone basics": [("staff", "caller"), ("caller", "staff")],
    "addresses & contact info": [("person A", "person B"), ("person B", "person A")],
    "job interview": [("interviewer", "candidate"), ("candidate", "interviewer")],  # Scene 専用
    "small talk at lobby": [("staff", "guest"), ("guest", "staff")],
    "making plans in lobby": [("person A", "person B"), ("person B", "person A")],
    "delivery and online shopping": [("support agent", "customer"), ("customer", "support agent")],
    "emergencies": [("staff", "person"), ("person", "staff")],
}

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
    "self_introduction", # 面接・自己紹介（Scene: job interview と組み合わせ）
    "talk_experience",   # 面接・過去経験
    "route_instruction", # 道案内：命令形の指示
    "",
]

# Functional/Scene → pattern の重み（学習需要＋自然さ）
PATTERN_WEIGHTS_BY_FUNCTIONAL: Dict[str, Dict[str, int]] = {
    "polite requests": {
        "polite_request": 6, "ask_permission": 4, "confirm_detail": 3, "make_suggestion": 2
    },
    "asking & giving directions": {
        "ask_direction": 6, "confirm_route": 4, "route_instruction": 4, "confirm_detail": 3, "polite_request": 2
    },
    "making plans": {
        "make_suggestion": 6, "ask_availability": 3, "confirm_detail": 3, "express_consequence": 2
    },
    "describing problems": {
        "confirm_detail": 5, "polite_request": 3, "give_advice": 3, "express_consequence": 2
    },
    # 面接の重みは Scene 側（下）に集約
    "restaurant ordering": {
        "polite_request": 4, "make_suggestion": 3, "confirm_detail": 3
    },
    "hotel check-in/out": {
        "confirm_detail": 4, "polite_request": 4
    },
}

# Scene 側のパターン重み（job interview をこちらに集約）
PATTERN_WEIGHTS_BY_FUNCTIONAL.update({
    "street directions": {"ask_direction": 6, "confirm_route": 4, "route_instruction": 4, "confirm_detail": 2},
    "job interview": {"self_introduction": 6, "talk_experience": 5, "express_opinion": 3, "confirm_detail": 2},
    "returns & exchanges": {"confirm_detail": 5, "polite_request": 4, "express_consequence": 2},
})

# 機能ごとの既定 POS バイアス（ENV未指定時に使うだけ。main.py が未対応でも無害）
DEFAULT_POS_BY_FUNCTIONAL: Dict[str, List[str]] = {
    "greetings & introductions": ["adjective", "noun"],
    "numbers & prices": ["noun", "adjective"],
    "time & dates": ["noun", "adverb"],
    "asking & giving directions": ["noun", "adverb", "verb"],
    "polite requests": ["verb", "modal", "adverb"],
    "offers & suggestions": ["verb", "noun"],
    "clarifying & confirming": ["verb", "noun"],
    "describing problems": ["noun", "verb", "adjective"],
    "apologizing & excuses": ["verb", "adverb"],
    "agreeing & disagreeing": ["verb", "adverb"],
    "preferences & opinions": ["verb", "noun", "adjective"],
    "making plans": ["verb", "noun"],
    "past experiences": ["verb", "adverb"],
    "future arrangements": ["verb", "noun", "adverb"],
    "comparisons": ["adjective", "adverb"],
    "frequency & habits": ["adverb", "verb", "noun"],
    "permission & ability": ["modal", "verb"],
    "cause & reason": ["conjunction", "adverb", "noun"],
    "condition & advice": ["conjunction", "verb"],
    "small talk starters": ["noun", "adjective"],
}

# 難易度ごとの functional・scene の重み（相対値）
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
        "polite requests": 3, "making plans": 3,
    },
    "B2": {
        "agreeing & disagreeing": 6, "preferences & opinions": 6,
        "cause & reason": 5, "condition & advice": 5,
        "comparisons": 4, "clarifying & confirming": 4,
        "describing problems": 4,
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
        "job interview": 5,  # 面接は Scene 側で難易度B1/B2寄り
    },
    "B2": {
        "emergencies": 6, "security & boarding": 5,
        "returns & exchanges": 5, "facilities & problems": 5,
        "delivery and online shopping": 4, "job interview": 6,
    },
}

# =========================
# ★ 追加: 難易度・語数の制御
# =========================
# DIFF_MODE: fixed / weighted / random（既定: weighted）
DIFF_MODE = os.getenv("DIFF_MODE", "weighted").strip().lower()
# DIFF_WEIGHTS 例: "A1:1,A2:2,B1:4,B2:2"
DIFF_WEIGHTS_ENV = os.getenv("DIFF_WEIGHTS", "A1:1,A2:2,B1:4,B2:2").strip()
# WORDS_BY_DIFF 例: "A1:8,A2:8,B1:6,B2:6"
WORDS_BY_DIFF_ENV = os.getenv("WORDS_BY_DIFF", "").strip()

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
    # デフォルト補完
    for k in ("A1", "A2", "B1", "B2"):
        out.setdefault(k, 0 if s else {"A1":1,"A2":2,"B1":4,"B2":2}[k])
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
    # CEFR_LEVEL があれば最優先（固定）
    env = os.getenv("CEFR_LEVEL", "").strip().upper()
    if env in ("A1", "A2", "B1", "B2"):
        return env
    # DIFF_MODE
    if DIFF_MODE == "fixed":
        # CEFR_LEVEL未指定でもfixedならB1固定（保守的）
        return "B1"
    if DIFF_MODE == "random":
        return rng.choice(["A1", "A2", "B1", "B2"])
    # weighted
    pool = []
    weights = []
    for k in ("A1", "A2", "B1", "B2"):
        pool.append(k)
        weights.append(max(0, DIFF_WEIGHTS.get(k, 0)))
    # 全部0ならB1
    if sum(weights) <= 0:
        return "B1"
    return rng.choices(pool, weights=weights, k=1)[0]

def _count_for_diff(diff: str) -> int:
    # VOCAB_WORDS が設定されていればそれを優先（既存の運用を壊さない）
    env_count = os.getenv("VOCAB_WORDS", "").strip()
    if env_count.isdigit():
        try:
            return max(1, int(env_count))
        except Exception:
            pass
    # 難易度別の既定（未指定は A1/A2:8, B1/B2:6）
    if WORDS_BY_DIFF:
        v = WORDS_BY_DIFF.get(diff.upper())
        if isinstance(v, int) and v > 0:
            return v
    return 8 if diff.upper() in ("A1", "A2") else 6

# =================================
# ユーティリティ（重み選択 / ENV）
# =================================
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
        "A1": {"polite_request": 3, "ask_permission": 2, "confirm_detail": 2, "ask_direction": 3, "confirm_route": 2, "route_instruction": 2},
        "A2": {"polite_request": 2, "confirm_detail": 2, "ask_availability": 2, "ask_direction": 3, "confirm_route": 2, "route_instruction": 2},
        "B1": {"give_advice": 3, "make_suggestion": 2, "express_opinion": 2, "self_introduction": 2, "talk_experience": 2},
        "B2": {"express_opinion": 3, "express_consequence": 2, "give_advice": 2, "self_introduction": 2, "talk_experience": 3},
    }
    for k, w in level_bias.get(level, {}).items():
        merged[k] = merged.get(k, 1) + w

    items = [(k, merged.get(k, 1)) for k in PATTERN_CANDIDATES]
    return _choose_weighted(items)

def _random_pos_from_env_or_default(functional: str) -> List[str]:
    v = os.getenv("VOCAB_POS", "").strip()
    if v:
        return [x.strip() for x in v.split(",") if x.strip()]
    return DEFAULT_POS_BY_FUNCTIONAL.get(functional, [])

def _random_difficulty() -> str:
    # 互換維持のため残すが、内部では _pick_difficulty() を使用
    return _pick_difficulty()

def _parse_csv_env(name: str) -> List[str]:
    v = os.getenv(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]

# ===========================
# 文脈（英語：指示用）
# ===========================
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
    if "small talk at lobby" in s:
        return "Two people start polite small talk in a hotel lobby."
    if "making plans in lobby" in s:
        return "Two people make simple plans in the lobby."

    # functional による汎用 fallback
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

# ===========================
# spec 構築（vocab / trend）
# ===========================
def _pick_roles(scene: str) -> Tuple[str, str]:
    pairs = ROLE_PAIRS_BY_SCENE.get(scene, [("person A", "person B")])
    return rng.choice(pairs)

def _build_spec(functional: str, scene: str, audio_lang: str) -> Dict[str, object]:
    """既存 main.py 互換のキーは維持しつつ、追加キー（role, family など）は“あってもなくても動く”形で付与する。"""
    # 役割
    role_from, role_to = _pick_roles(scene)
    # pattern
    pattern = _pick_pattern(functional, scene)
    # 既定POS（ENV優先）
    pos = _random_pos_from_env_or_default(functional)
    # 難易度（重み付きランダム/固定/ランダム）
    difficulty = _pick_difficulty()
    # 語数：VOCAB_WORDSがあればそれを優先、なければ難易度別既定
    count = _count_for_diff(difficulty)

    # relation_mode 既定（ENVがあればそれを使う）
    rel_env = os.getenv("RELATION_MODE", "").strip().lower()
    if rel_env:
        relation_mode = rel_env
    else:
        # 機能軸の学習回は functional_family、場所依存が強いときは scene_related
        if functional in ("greetings & introductions", "agreeing & disagreeing", "preferences & opinions",
                          "comparisons", "cause & reason", "condition & advice", "clarifying & confirming",
                          "polite requests", "offers & suggestions"):
            relation_mode = "functional_family"
        elif scene in ("hotel check-in/out", "restaurant ordering", "street directions", "returns & exchanges",
                       "transport tickets", "paying & receipts", "job interview", "facilities & problems"):
            relation_mode = "scene_related"
        else:
            relation_mode = ""

    # family（任意）：UIやタグ表示などで使える“シリーズ名”
    family = ""
    if functional == "greetings & introductions":
        family = "greetings_feelings"
    elif functional == "asking & giving directions":
        family = "directions_navigation"
    elif functional == "polite requests":
        family = "polite_request"
    elif functional == "clarifying & confirming":
        family = "clarification_confirm"
    elif functional == "offers & suggestions":
        family = "offering_suggestion"
    elif functional == "describing problems":
        family = "problem_reporting"
    elif functional == "numbers & prices":
        family = "time_price_numbers"

    theme = f"{functional} – {scene}"
    spec = {
        # === 既存互換キー（main.py が参照） ===
        "theme": theme,
        "context": _context_for_theme(functional, scene),
        "count": count,
        "pos": pos,                                     # POS は ENV 優先、未指定なら既定
        "relation_mode": relation_mode,                 # functional_family / scene_related / ""（既存コードが見ても問題なし）
        "difficulty": difficulty,
        "pattern_hint": pattern,                        # 既存 main.py のプロンプト強化に有効
        "morphology": _parse_csv_env("MORPHOLOGY"),

        # === 追加情報（main.py 未対応でも無害） ===
        "functional": functional,
        "scene": scene,
        "role_from": role_from,
        "role_to": role_to,
        "family": family,
    }
    return validate_spec(spec)

# ========== バリデーション（整合性の最終チェック） ==========
def validate_spec(spec: Dict[str, object]) -> Dict[str, object]:
    """機能↔シーン↔パターン↔役割 の整合性を軽く担保。破壊的変更はせず安全側に寄せる。"""
    functional = str(spec.get("functional") or "")
    scene = str(spec.get("scene") or "")
    pattern = str(spec.get("pattern_hint") or "")

    # 役割：シーンに無い組み合わせなら差し替え
    rf, rt = str(spec.get("role_from") or ""), str(spec.get("role_to") or "")
    valid_pairs = ROLE_PAIRS_BY_SCENE.get(scene)
    if valid_pairs:
        if (rf, rt) not in valid_pairs:
            new_rf, new_rt = rng.choice(valid_pairs)
            spec["role_from"], spec["role_to"] = new_rf, new_rt

    # パターン：機能・シーンの推奨に置き直し（空or不整合なら）
    if not pattern or pattern not in PATTERN_CANDIDATES:
        spec["pattern_hint"] = _pick_pattern(functional, scene)

    # POS：ENV未指定かつ空なら既定を入れる
    if not spec.get("pos"):
        spec["pos"] = DEFAULT_POS_BY_FUNCTIONAL.get(functional, [])

    # relation_mode：空で、明らかにシーン依存なら scene_related を推奨
    if not spec.get("relation_mode"):
        if scene in ("hotel check-in/out", "restaurant ordering", "street directions", "returns & exchanges",
                     "transport tickets", "paying & receipts", "job interview", "facilities & problems"):
            spec["relation_mode"] = "scene_related"

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
        "relation_mode": "trend_related",
        "difficulty": level,
        "pattern_hint": _trend_pattern_hint(audio_lang),
        "morphology": [],
        "trend": True,

        # 追加（無害）
        "functional": "trend_topic",
        "scene": "general news talk",
        "role_from": "person A",
        "role_to": "person B",
        "family": "trend_related",
    }
    return validate_spec(spec)

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
      - ★ DIFF_MODE=fixed/weighted/random（既定: weighted）
      - ★ DIFF_WEIGHTS="A1:1,A2:2,B1:4,B2:2"
      - ★ WORDS_BY_DIFF="A1:8,A2:8,B1:6,B2:6"

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
                "count": _count_for_diff(_pick_difficulty()),
                "pos": [],
                "relation_mode": "",
                "difficulty": _pick_difficulty(),
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
    print("— vocab (string) —")
    print(pick_by_content_type("vocab", "en"))
    print("— vocab (spec) —")
    print(pick_by_content_type("vocab", "en", return_context=True))
    print("— trend (string) —")
    print(pick_by_content_type("vocab_trend", "en"))
    print("— trend (spec) —")
    print(pick_by_content_type("vocab_trend", "en", return_context=True))