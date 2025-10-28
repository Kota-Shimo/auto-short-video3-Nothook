# topic_picker.py – vocab専用のテーマを日替わりで返す（CEFR重み付き・学習本質寄り）
import os
import random
import datetime

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
    （モデルへの指示用なので英語固定／出力言語は別で指定される想定）
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

def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    vocab の場合に、学習本質に沿ったテーマを日替わりで1つ返す。
    - CEFR_LEVEL（A1/A2/B1）で機能系とシーン系の比率を変更
    - UTC日付 + audio_lang で毎日安定した結果（言語ごとに独立ローテ）
    return_context=True の場合は (theme, context) を返す（後方互換のため既定は False）。
    それ以外の content_type が来た場合は汎用値を返す。
    """
    ct = (content_type or "vocab").lower()
    if ct != "vocab":
        return ("general vocabulary", _context_for_theme("general vocabulary")) if return_context else "general vocabulary"

    level = os.getenv("CEFR_LEVEL", "A2").upper()
    # 日替わり安定シード（言語ごとに独立）
    today_seed = int(datetime.date.today().strftime("%Y%m%d")) + (hash(audio_lang) % 1000)
    rng = random.Random(today_seed)

    # 学習段階に応じた重み付け
    if level == "A1":
        pool = (VOCAB_THEMES_FUNCTIONAL * 7) + (VOCAB_THEMES_SCENE * 3)
    elif level == "B1":
        pool = (VOCAB_THEMES_FUNCTIONAL * 4) + (VOCAB_THEMES_SCENE * 6)
    else:  # 既定 A2
        pool = (VOCAB_THEMES_FUNCTIONAL * 5) + (VOCAB_THEMES_SCENE * 5)

    theme = rng.choice(pool)
    if return_context:
        return theme, _context_for_theme(theme)
    return theme

# ローカルテスト用
if __name__ == "__main__":
    # 後方互換（テーマのみ）
    print(pick_by_content_type("vocab", "en"))
    # 文脈つき
    print(pick_by_content_type("vocab", "en", return_context=True))