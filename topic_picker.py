# topic_picker.py – vocab専用のテーマをランダム返却（CEFR重み付き・学習本質寄り + 拡張spec）
import os
import random

# ==== vocab 用の最適化テーマ ====
# 機能別（Functional）：伝えたいことが言える中核スキル
VOCAB_THEMES_FUNCTIONAL = [
    "greetings & introductions", "numbers & prices", "time & dates",
    "asking & giving directions", "polite requests", "offers & suggestions",
    "clarifying & confirming", "describing problems", "apologizing & excuses",
    "agreeing & disagreeing", "preferences & opinions", "making plans",
    "past experiences", "future arrangements", "comparisons",
    "frequency & habits", "permission & ability", "cause & reason",
    "condition & advice", "small talk starters",
]

# シーン別（Scene）：高頻度の具体場面で使う語彙
VOCAB_THEMES_SCENE = [
    "shopping basics", "paying & receipts", "returns & exchanges",
    "restaurant ordering", "dietary needs", "transport tickets",
    "airport check-in", "security & boarding", "hotel check-in/out",
    "facilities & problems", "appointments", "pharmacy basics",
    "emergencies", "delivery and online shopping", "phone basics",
    "addresses & contact info",
]

def _context_for_theme(theme: str) -> str:
    """
    例文生成の安定化用に、テーマに合う超短いシーン文脈を英語で返す。
    （モデルへの指示用なので英語固定／出力言語は別で指定）
    """
    t = (theme or "").lower()

    # --- Scene 系の文脈 ---
    if "hotel" in t:
        return "A guest talks to the hotel front desk about a simple request."
    if "restaurant" in t:
        return "A customer orders food and asks simple questions at a restaurant."
    if "dietary" in t:
        return "A diner explains a simple dietary need to staff."
    if "shopping" in t:
        return "A customer asks for items and prices in a store."
    if "paying" in t or "receipts" in t:
        return "A customer pays and asks for a receipt at the counter."
    if "returns" in t or "exchanges" in t:
        return "A customer politely asks to return or exchange an item."
    if "airport" in t or "boarding" in t or "security" in t:
        return "A traveler checks in at the airport and asks a brief question."
    if "transport" in t or "tickets" in t:
        return "A traveler buys a ticket and asks for the right line."
    if "facilities" in t or "problems" in t:
        return "A guest reports a small problem and asks for help."
    if "appointments" in t:
        return "A person makes or confirms a simple appointment time."
    if "pharmacy" in t:
        return "A customer asks for basic medicine at a pharmacy."
    if "emergencies" in t:
        return "A person quickly explains a simple urgent situation."
    if "delivery" in t or "online shopping" in t:
        return "A customer checks delivery status or address details."
    if "phone basics" in t or "phone" in t:
        return "A caller asks a simple question on the phone."
    if "addresses" in t or "contact" in t:
        return "Two people exchange addresses or contact information."

    # --- Functional 系の文脈 ---
    if "greetings" in t or "introductions" in t:
        return "Two people meet for the first time and introduce themselves."
    if "numbers" in t or "prices" in t:
        return "A buyer asks the price and understands simple numbers."
    if "time" in t or "dates" in t:
        return "People check the time or set a simple date."
    if "directions" in t:
        return "Someone asks how to get to a nearby place."
    if "polite requests" in t:
        return "Someone politely asks for a small favor or item."
    if "offers" in t or "suggestions" in t:
        return "A person makes a friendly suggestion."
    if "clarifying" in t or "confirming" in t:
        return "People clarify a small detail to avoid confusion."
    if "describing problems" in t:
        return "Someone explains a small issue and asks for help."
    if "apologizing" in t or "excuses" in t:
        return "Someone says sorry briefly for a small mistake."
    if "agreeing" in t or "disagreeing" in t:
        return "People show simple agreement or polite disagreement."
    if "preferences" in t or "opinions" in t:
        return "Someone says what they like or prefer."
    if "making plans" in t:
        return "Two friends plan a simple meetup."
    if "past experiences" in t:
        return "Someone shares a short past experience."
    if "future arrangements" in t:
        return "People schedule something in the near future."
    if "comparisons" in t:
        return "A person compares two options briefly."
    if "frequency" in t or "habits" in t:
        return "Someone talks about how often they do something."
    if "permission" in t or "ability" in t:
        return "A person asks for permission or says they can/can't."
    if "cause" in t or "reason" in t:
        return "Someone gives a short reason for something."
    if "condition" in t or "advice" in t:
        return "A person gives a simple if-advice."
    if "small talk" in t:
        return "Two people start light small talk."

    # デフォルト文脈
    return "A simple everyday situation with polite, practical language."


# === 難易度に連動してテーマを選ぶ（比率違いのプールから抽選） ===
def _pick_theme_for_level(level: str) -> str:
    """
    level（A1/A2/B1/B2）に応じて、機能系/シーン系の比率を変えてプールを作り、そこからランダム選択。
    THEME_OVERRIDE があればそちらを最優先。
    """
    override = os.getenv("THEME_OVERRIDE", "").strip()
    if override:
        return override

    lv = (level or "A2").upper()
    if lv == "A1":
        pool = (VOCAB_THEMES_FUNCTIONAL * 7) + (VOCAB_THEMES_SCENE * 3)
    elif lv == "B1":
        pool = (VOCAB_THEMES_FUNCTIONAL * 4) + (VOCAB_THEMES_SCENE * 6)
    elif lv == "B2":
        pool = (VOCAB_THEMES_FUNCTIONAL * 6) + (VOCAB_THEMES_SCENE * 4)
    else:  # 既定 A2
        pool = (VOCAB_THEMES_FUNCTIONAL * 5) + (VOCAB_THEMES_SCENE * 5)

    rng = random.SystemRandom()
    return rng.choice(pool)


def _relation_mode_of_day(audio_lang: str) -> str:
    """
    relation_mode を毎回ランダムに選択（synonym / antonym / collocation / pattern / ""）
    - RELATION_MODE 環境変数があればそれを最優先
    """
    env = os.getenv("RELATION_MODE", "").strip().lower()
    if env:
        return env

    rng = random.SystemRandom()
    modes = ["synonym", "collocation", "pattern", "antonym", ""]
    return rng.choice(modes)


def _parse_csv_env(name: str):
    v = os.getenv(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


# === ランダム選択ヘルパ ===
def _random_pos():
    """ENV未指定なら、単一品詞 or 指定なしをランダム選択（後方互換：ENV指定があればそれを優先）。"""
    env = _parse_csv_env("VOCAB_POS")
    if env:
        return env
    rng = random.SystemRandom()
    return rng.choice([[], ["noun"], ["verb"], ["adjective"]])


def _random_difficulty():
    """
    ENV未指定なら A2/B1/B2 からランダム。
    少し“背伸び語彙”を混ぜたいので A1 はデフォルト抽選から外す（ENV指定でA1固定は可）。
    """
    env = os.getenv("CEFR_LEVEL", "").strip().upper()
    if env in ("A1", "A2", "B1", "B2"):
        return env
    rng = random.SystemRandom()
    return rng.choice(["A2", "B1", "B2"])


def _random_pattern_hint():
    """ENV未指定なら、汎用パターン意図をランダム選択（空も混ぜてバリエーション確保）。"""
    env = os.getenv("PATTERN_HINT", "").strip()
    if env:
        return env
    rng = random.SystemRandom()
    pool = [
        "",  # 指定なし
        "polite_request",      # please / could / would
        "ask_permission",      # may I / can I
        "ask_availability",    # available / time / slot
        "confirm_detail",      # confirm / double-check
        "make_suggestion",     # would like / maybe / how about
        "give_advice",         # should / recommend / better to
        "express_opinion",     # I think / I prefer
        "express_consequence", # therefore / so / accordingly
    ]
    return rng.choice(pool)


def _build_spec(theme: str, audio_lang: str, difficulty: str) -> dict:
    """
    spec を構築（ENV最優先・未指定はランダム）:
    - pos: [], ["noun"], ["verb"], ["adjective"] のいずれか
    - difficulty: pick時に決めた難易度（A1〜B2）
    - pattern_hint: 上記パターンのいずれか（空含む）
    """
    spec = {
        "theme": theme,
        "context": _context_for_theme(theme),
        "count": int(os.getenv("VOCAB_WORDS", "6")),
        "pos": _random_pos(),
        "relation_mode": _relation_mode_of_day(audio_lang),
        "difficulty": (difficulty or "A2").upper(),
        "pattern_hint": _random_pattern_hint(),
        "morphology": _parse_csv_env("MORPHOLOGY"),  # 既存互換：必要ならENVで指定
    }
    return spec


def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    vocab の場合に、学習本質に沿ったテーマと spec を返す。
    フロー:
      1) 難易度を決める（CEFR_LEVELのENV固定 or ランダム）
      2) 難易度に連動してテーマを抽選（機能系/シーン系の比率を変更）
      3) return_context=True なら、その難易度を spec.difficulty に入れて返す

    return_context=False:  従来互換 → テーマ文字列を返す
    return_context=True:   拡張     → 辞書specを返す（theme/context/count/pos/relation_mode/difficulty/pattern_hint/morphology）
    """
    ct = (content_type or "vocab").lower()

    # 1) 難易度を決定（ENV優先・未指定は A2/B1/B2 のランダム）
    difficulty = _random_difficulty()

    if ct != "vocab":
        if return_context:
            theme = "general vocabulary"
            return {
                "theme": theme,
                "context": _context_for_theme(theme),
                "count": int(os.getenv("VOCAB_WORDS", "6")),
                "pos": [],
                "relation_mode": "",
                "difficulty": difficulty,
                "pattern_hint": _random_pattern_hint(),
                "morphology": [],
            }
        return "general vocabulary"

    # 2) 難易度に連動してテーマを抽選
    theme = _pick_theme_for_level(difficulty)

    if not return_context:
        return theme

    # 3) 拡張：spec を返す（main.py が dict をそのまま扱える）
    return _build_spec(theme, audio_lang, difficulty)


# ローカルテスト用
if __name__ == "__main__":
    # 後方互換（テーマのみ）
    print(pick_by_content_type("vocab", "en"))
    # 拡張spec
    print(pick_by_content_type("vocab", "en", return_context=True))