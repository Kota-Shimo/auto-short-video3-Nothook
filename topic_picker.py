# topic_picker.py – Functional→Scene の二段選択（CEFR重み付き）+ 拡張spec
import os
import random

# ─────────────────────────────────────────
# Functional: 伝達機能（抽象機能） / Scene: 具体シチュエーション
# ─────────────────────────────────────────
VOCAB_THEMES_FUNCTIONAL = [
    "greetings & introductions", "numbers & prices", "time & dates",
    "asking & giving directions", "polite requests", "offers & suggestions",
    "clarifying & confirming", "describing problems", "apologizing & excuses",
    "agreeing & disagreeing", "preferences & opinions", "making plans",
    "past experiences", "future arrangements", "comparisons",
    "frequency & habits", "permission & ability", "cause & reason",
    "condition & advice", "small talk starters",
]

VOCAB_THEMES_SCENE = [
    "shopping basics", "paying & receipts", "returns & exchanges",
    "restaurant ordering", "dietary needs", "transport tickets",
    "airport check-in", "security & boarding", "hotel check-in/out",
    "facilities & problems", "appointments", "pharmacy basics",
    "emergencies", "delivery and online shopping", "phone basics",
    "addresses & contact info",
]

# Functional → 相性の良い Scene 候補（不足時は全 Scene から抽選）
COMPAT_SCENES = {
    "greetings & introductions": ["hotel check-in/out", "restaurant ordering", "shopping basics", "phone basics"],
    "numbers & prices":          ["shopping basics", "paying & receipts", "transport tickets"],
    "time & dates":              ["appointments", "transport tickets", "restaurant ordering"],
    "asking & giving directions":["transport tickets", "airport check-in", "hotel check-in/out"],
    "polite requests":           ["restaurant ordering", "hotel check-in/out", "shopping basics", "facilities & problems"],
    "offers & suggestions":      ["restaurant ordering", "making plans", "shopping basics"],
    "clarifying & confirming":   ["hotel check-in/out", "paying & receipts", "appointments", "security & boarding"],
    "describing problems":       ["facilities & problems", "pharmacy basics", "returns & exchanges"],
    "apologizing & excuses":     ["hotel check-in/out", "restaurant ordering", "returns & exchanges"],
    "agreeing & disagreeing":    ["making plans", "restaurant ordering"],
    "preferences & opinions":    ["restaurant ordering", "shopping basics", "dietary needs"],
    "making plans":              ["appointments", "restaurant ordering"],
    "past experiences":          ["small talk starters", "hotel check-in/out"],
    "future arrangements":       ["appointments", "transport tickets", "delivery and online shopping"],
    "comparisons":               ["shopping basics", "transport tickets"],
    "frequency & habits":        ["small talk starters", "pharmacy basics"],
    "permission & ability":      ["security & boarding", "facilities & problems"],
    "cause & reason":            ["returns & exchanges", "apologies & excuses" if "apologies & excuses" in VOCAB_THEMES_FUNCTIONAL else "facilities & problems"],
    "condition & advice":        ["pharmacy basics", "dietary needs", "returns & exchanges"],
    "small talk starters":       ["hotel check-in/out", "restaurant ordering", "airport check-in"],
}

# ─────────────────────────────────────────
# 文脈（例文の安定化用）。英語で短く返す（モデル指示用）
# ─────────────────────────────────────────
def _context_for_scene(scene: str) -> str:
    s = (scene or "").lower()
    if "hotel" in s:           return "A guest talks to the hotel front desk about a simple request."
    if "restaurant" in s:      return "A customer orders food and asks simple questions at a restaurant."
    if "dietary" in s:         return "A diner explains a simple dietary need to staff."
    if "shopping" in s:        return "A customer asks for items and prices in a store."
    if "paying" in s or "receipt" in s:  return "A customer pays and asks for a receipt at the counter."
    if "returns" in s:         return "A customer politely asks to return or exchange an item."
    if "airport" in s:         return "A traveler checks in at the airport and asks a brief question."
    if "security" in s:        return "A traveler follows security instructions and asks something simple."
    if "transport" in s:       return "A traveler buys a ticket and asks for the right line."
    if "facilities" in s:      return "A guest reports a small problem and asks for help."
    if "appointments" in s:    return "A person makes or confirms a simple appointment time."
    if "pharmacy" in s:        return "A customer asks for basic medicine at a pharmacy."
    if "emergencies" in s:     return "A person quickly explains a simple urgent situation."
    if "delivery" in s:        return "A customer checks delivery status or address details."
    if "phone" in s:           return "A caller asks a simple question on the phone."
    if "addresses" in s or "contact" in s: return "Two people exchange addresses or contact information."
    return "A simple everyday situation with polite, practical language."

def _hint_for_functional(func: str) -> str:
    f = (func or "").lower()
    if "greetings" in f:        return "Use friendly openers suitable for first-time meetings."
    if "numbers" in f:          return "Include simple numbers or prices naturally."
    if "time" in f:             return "Include time or date expressions briefly."
    if "directions" in f:       return "Use short phrases to ask or give directions."
    if "polite requests" in f:  return "Prefer could/would or other polite request forms."
    if "offers" in f:           return "Suggest simple options politely."
    if "clarifying" in f:       return "Confirm or clarify a small detail."
    if "describing problems" in f: return "State a small problem and ask for help briefly."
    if "apologizing" in f:      return "Include a brief apology."
    if "agreeing" in f:         return "Show simple agreement or disagreement politely."
    if "preferences" in f:      return "Express a simple preference or opinion."
    if "making plans" in f:     return "Arrange a simple plan with short phrases."
    if "past experiences" in f: return "Refer briefly to a past event."
    if "future arrangements" in f: return "Schedule something in the near future."
    if "comparisons" in f:      return "Compare two options briefly."
    if "frequency" in f:        return "Mention how often something happens."
    if "permission" in f:       return "Ask for permission or ability in a short phrase."
    if "cause" in f:            return "Give a short reason with natural connectors."
    if "condition" in f:        return "Give simple if-conditions as advice."
    if "small talk" in f:       return "Keep it light and friendly."
    return ""

# ─────────────────────────────────────────
# 乱数ユーティリティ
# ─────────────────────────────────────────
def _rng():
    return random.SystemRandom()

def _parse_csv_env(name: str):
    v = os.getenv(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]

# ─────────────────────────────────────────
# CEFR に応じた Functional/Scene の重み（まず Functional を選ぶ）
# ─────────────────────────────────────────
def _pick_functional_for_level():
    level = os.getenv("CEFR_LEVEL", "A2").upper()
    r = _rng()
    # A1 は Functional を強め、B1 は Scene 寄りだが「まず Functional を選ぶ」方針は固定
    if level == "A1":
        pool = VOCAB_THEMES_FUNCTIONAL * 8
    elif level == "B1":
        pool = VOCAB_THEMES_FUNCTIONAL * 5
    elif level == "B2":
        pool = VOCAB_THEMES_FUNCTIONAL * 6
    else:  # A2
        pool = VOCAB_THEMES_FUNCTIONAL * 6
    # 固定オーバーライド
    ov = os.getenv("FUNC_OVERRIDE", "").strip()
    if ov and ov in VOCAB_THEMES_FUNCTIONAL:
        return ov
    return r.choice(pool)

def _pick_scene_for_functional(func: str):
    level = os.getenv("CEFR_LEVEL", "A2").upper()
    r = _rng()
    # 互換候補
    compat = COMPAT_SCENES.get(func, [])
    # レベルで Scene の一般プールを微調整（難度が上がると Scene の幅を少し広げる）
    if level == "A1":
        general = VOCAB_THEMES_SCENE * 3
    elif level == "B1":
        general = VOCAB_THEMES_SCENE * 6
    elif level == "B2":
        general = VOCAB_THEMES_SCENE * 5
    else:  # A2
        general = VOCAB_THEMES_SCENE * 5

    # オーバーライド
    ov = os.getenv("SCENE_OVERRIDE", "").strip()
    if ov and ov in VOCAB_THEMES_SCENE:
        return ov

    pool = (compat * 4) + general  # 互換シーンを厚めに
    return r.choice(pool) if pool else r.choice(VOCAB_THEMES_SCENE)

# ─────────────────────────────────────────
# 仕様（spec）作成：ENV最優先 → 未指定はランダム
# ─────────────────────────────────────────
def _random_pos():
    env = _parse_csv_env("VOCAB_POS")
    if env:
        return env
    return _rng().choice([[], ["noun"], ["verb"], ["adjective"]])

def _random_difficulty():
    env = os.getenv("CEFR_LEVEL", "").strip().upper()
    if env in ("A1", "A2", "B1", "B2"):
        return env
    return _rng().choice(["A2", "B1", "B2"])

def _random_relation_mode(audio_lang: str):
    env = os.getenv("RELATION_MODE", "").strip().lower()
    if env:
        return env
    return _rng().choice(["synonym", "collocation", "pattern", "antonym", ""])

def _random_pattern_hint():
    env = os.getenv("PATTERN_HINT", "").strip()
    if env:
        return env
    return _rng().choice([
        "", "polite_request", "ask_permission", "ask_availability",
        "confirm_detail", "make_suggestion", "give_advice",
        "express_opinion", "express_consequence",
    ])

def _build_theme_label(functional: str, scene: str) -> str:
    # タイトル等でわかりやすい結合名
    # 例: "polite requests (restaurant ordering)"
    if scene:
        return f"{functional} ({scene})"
    return functional

def _build_context(functional: str, scene: str) -> str:
    # Scene の文脈 + Functional のヒントを結合（モデル指示用）
    scene_ctx = _context_for_scene(scene)
    func_hint = _hint_for_functional(functional)
    if func_hint:
        return f"{scene_ctx} Keep the functional focus: {func_hint}"
    return scene_ctx

def _build_spec(functional: str, scene: str, audio_lang: str) -> dict:
    return {
        "theme": _build_theme_label(functional, scene),
        "functional": functional,                # 参考用メタ（main.py は無視してもOK）
        "scene": scene,                          # 参考用メタ
        "context": _build_context(functional, scene),
        "count": int(os.getenv("VOCAB_WORDS", "6")),
        "pos": _random_pos(),
        "relation_mode": _random_relation_mode(audio_lang),
        "difficulty": _random_difficulty(),
        "pattern_hint": _random_pattern_hint(),
        "morphology": _parse_csv_env("MORPHOLOGY"),
    }

# ─────────────────────────────────────────
# 公開API
# ─────────────────────────────────────────
def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    vocab 専用：
      1) Functional を CEFR 重み付きで選択
      2) その Functional と相性の良い Scene を選択（不足時は汎用 Scene プール）
      3) Functional×Scene を併記した theme と、両者を反映した context/spec を返す

    ENV（任意）:
      - CEFR_LEVEL = A1/A2/B1/B2
      - FUNC_OVERRIDE / SCENE_OVERRIDE / THEME_OVERRIDE（※THEME_OVERRIDE優先）
      - VOCAB_POS="noun,verb" / RELATION_MODE / PATTERN_HINT / MORPHOLOGY="prefix:un-"
    """

    # 旧来の完全上書き（互換目的）
    theme_override = os.getenv("THEME_OVERRIDE", "").strip()
    if theme_override:
        if return_context:
            # override ではシンプルな context を付与
            return {
                "theme": theme_override,
                "functional": "",
                "scene": "",
                "context": _context_for_scene(theme_override),
                "count": int(os.getenv("VOCAB_WORDS", "6")),
                "pos": _random_pos(),
                "relation_mode": _random_relation_mode(audio_lang),
                "difficulty": _random_difficulty(),
                "pattern_hint": _random_pattern_hint(),
                "morphology": _parse_csv_env("MORPHOLOGY"),
            }
        return theme_override

    ct = (content_type or "vocab").lower()
    if ct != "vocab":
        # 他タイプが来た場合の穏当な既定値
        base = "general vocabulary"
        if return_context:
            return {
                "theme": base,
                "functional": "",
                "scene": "",
                "context": _context_for_scene(base),
                "count": int(os.getenv("VOCAB_WORDS", "6")),
                "pos": [],
                "relation_mode": "",
                "difficulty": _random_difficulty(),
                "pattern_hint": _random_pattern_hint(),
                "morphology": [],
            }
        return base

    functional = _pick_functional_for_level()
    scene = _pick_scene_for_functional(functional)
    theme = _build_theme_label(functional, scene)

    if not return_context:
        return theme

    return _build_spec(functional, scene, audio_lang)

# ローカルデバッグ
if __name__ == "__main__":
    print(pick_by_content_type("vocab", "en"))                      # 例: "polite requests (restaurant ordering)"
    print(pick_by_content_type("vocab", "en", return_context=True)) # spec 全体