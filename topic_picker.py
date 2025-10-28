# topic_picker.py – vocab専用のテーマを日替わりで返す（CEFR重み＋学習者需要寄り）
import os
import random
import datetime

# ========== Buckets ==========
# 1) 動詞クラスター（使い分けで迷う代表）
THEMES_VERB_CLUSTERS = [
    "go / come / leave / arrive",
    "say / tell / talk / speak",
    "make / do / take / have",
    "look / see / watch",
    "put / set / leave / keep",
    "bring / take / get / fetch",
    "give / send / pass / hand",
    "find / look for / discover",
    "start / begin / finish / end",
    "ask / request / demand / require",
]

# 2) コロケーション & フレーズ（“単語＋型”で使える）
THEMES_COLLOCATIONS = [
    "make / do collocations (make a reservation, do homework)",
    "get collocations (get ready, get lost, get better)",
    "take collocations (take a break, take a seat, take care)",
    "give collocations (give advice, give a call, give permission)",
    "have collocations (have a look, have a try, have trouble)",
    "travel phrasal verbs (check in, set off, get on/off)",
    "daily phrasal verbs (pick up, put off, turn on/off)",
    "asking directions phrases (go straight, turn left/right)",
    "apologizing & softening phrases (sorry to bother you, would you mind)",
    "clarifying phrases (do you mean…, so you’re saying…)",
]

# 3) コミュニケーション機能（意図が伝わる表現）
THEMES_COMMUNICATION_ACTS = [
    "polite requests",
    "offers & suggestions",
    "clarifying & confirming",
    "apologizing & excuses",
    "agreeing & disagreeing",
    "preferences & opinions",
    "making plans & invitations",
    "giving advice & recommendations",
    "expressing reasons & causes",
    "conditions & possibilities",
]

# 4) 高頻度シーン（言語横断で需要大）
THEMES_SCENE = [
    "greetings & introductions",
    "small talk starters",
    "numbers & prices",
    "time & dates",
    "asking & giving directions",
    "shopping essentials",
    "restaurant ordering",
    "transport tickets & routes",
    "appointments & schedules",
    "phone basics",
    "pharmacy & simple health",
    "emergencies (simple)",
]

# 5) 文法機能ミニテーマ（初中級で効く）
THEMES_GRAMMAR_FUNCTIONS = [
    "frequency & habits (always, usually, sometimes)",
    "ability & permission (can, could, may)",
    "past experiences (present perfect basics)",
    "future arrangements (be going to / will / present continuous)",
    "comparisons (comparatives & superlatives)",
    "quantifiers (some, any, much, many, a lot of)",
    "time markers (already, yet, just, still, soon)",
    "sequencing (first, then, finally)",
    "intensifiers & softeners (really, quite, a bit)",
    "linking words (because, so, but, although)",
]

# === 需要寄り Top 群（重みを強めに） ===
TOP_PRIORITY = [
    # Verb clusters & Collocations（迷いやすく汎用性が高い）
    "make / do / take / have",
    "say / tell / talk / speak",
    "go / come / leave / arrive",
    "get collocations (get ready, get lost, get better)",
    "take collocations (take a break, take a seat, take care)",
    "travel phrasal verbs (check in, set off, get on/off)",
    "daily phrasal verbs (pick up, put off, turn on/off)",
    # Communication acts（会話で“使う”）
    "polite requests",
    "clarifying & confirming",
    "making plans & invitations",
    "giving advice & recommendations",
    # Scene（万人向け・高頻度）
    "asking & giving directions",
    "restaurant ordering",
    "shopping essentials",
    "phone basics",
    "time & dates",
    # Grammar functions（初中級の壁を越える）
    "ability & permission (can, could, may)",
    "frequency & habits (always, usually, sometimes)",
    "comparisons (comparatives & superlatives)",
    "linking words (because, so, but, although)",
]

# ---------- 文脈ヒント ----------
def _context_for_theme(theme: str) -> str:
    """
    例文生成の安定化用に、テーマに合う超短い英語のシーン文脈を返す。
    出力言語は別で制御される想定。英語固定でOK。
    """
    t = (theme or "").lower()

    # Verb clusters
    if "go / come / leave / arrive" in t:
        return "Two people talk about moving from one place to another."
    if "say / tell / talk / speak" in t:
        return "Someone reports information and checks they used the right verb."
    if "make / do / take / have" in t:
        return "A person describes daily tasks using set phrases."
    if "look / see / watch" in t:
        return "Someone describes how they perceive or view something."
    if "put / set / leave / keep" in t:
        return "Someone places an item and explains what to do with it."
    if "bring / take / get / fetch" in t:
        return "A person asks about moving items from place to place."
    if "give / send / pass / hand" in t:
        return "A person transfers something to another person."
    if "find / look for / discover" in t:
        return "Someone searches for a missing item."
    if "start / begin / finish / end" in t:
        return "A person talks about starting or finishing an activity."
    if "ask / request / demand / require" in t:
        return "Someone politely asks for what they need."

    # Collocations & phrases
    if "collocations" in t or "phrasal verbs" in t:
        return "The speaker uses a common set phrase in a simple situation."
    if "directions" in t:
        return "A person asks how to get to a nearby place."
    if "apologizing" in t or "softening" in t:
        return "Someone softens a request and says sorry politely."
    if "clarifying" in t:
        return "Two people confirm a small detail to avoid confusion."

    # Communication acts
    if "polite requests" in t:
        return "A person asks for a small favor politely."
    if "offers & suggestions" in t:
        return "A person suggests a simple idea to help."
    if "making plans" in t or "invitations" in t:
        return "Two people arrange a simple meetup."
    if "advice" in t or "recommendations" in t:
        return "Someone gives a short piece of useful advice."
    if "reasons" in t or "causes" in t:
        return "A person explains a short reason."
    if "conditions" in t or "possibilities" in t:
        return "A person gives a simple if-advice."

    # Scene
    if "greetings" in t or "introductions" in t:
        return "Two people meet and introduce themselves."
    if "small talk" in t:
        return "Two people start a short, friendly chat."
    if "numbers" in t or "prices" in t:
        return "A buyer asks the price at a store."
    if "time" in t or "dates" in t:
        return "People check the time or a meeting date."
    if "shopping" in t:
        return "A customer looks for items and asks prices."
    if "restaurant" in t:
        return "A customer orders simply at a restaurant."
    if "transport" in t or "routes" in t or "tickets" in t:
        return "A traveler buys a ticket and asks which line to take."
    if "appointments" in t or "schedules" in t:
        return "A person confirms a simple appointment time."
    if "phone" in t:
        return "A caller asks a quick question on the phone."
    if "pharmacy" in t or "health" in t:
        return "A customer asks for basic medicine at a pharmacy."
    if "emergencies" in t:
        return "A person explains a simple urgent situation."

    # Grammar functions
    if "frequency" in t:
        return "A person describes routine activities."
    if "ability" in t or "permission" in t:
        return "A person asks for permission or says they can do something."
    if "past experiences" in t:
        return "Someone briefly shares something they have done before."
    if "future arrangements" in t:
        return "People schedule a plan in the near future."
    if "comparisons" in t:
        return "Someone compares two options briefly."
    if "quantifiers" in t:
        return "A person describes how much or how many they need."
    if "time markers" in t:
        return "A person mentions timing like already or yet."
    if "sequencing" in t:
        return "A person explains steps in order."
    if "intensifiers" in t or "softeners" in t:
        return "A person softens or strengthens their statement."
    if "linking words" in t:
        return "A person links two ideas with a simple connector."

    # Default
    return "A simple everyday situation with polite, practical language."

# ---------- ピッカー本体 ----------
def pick_by_content_type(content_type: str, audio_lang: str, return_context: bool = False):
    """
    vocab の場合に、学習本質に沿ったテーマを日替わりで1つ返す。
    - CEFR_LEVEL（A1/A2/B1）でバケット重み変更
    - UTC日付 + audio_lang で毎日安定（言語ごとに独立ローテ）
    - FORCE_THEME / FORCE_BUCKET で強制指定可能（開発・検証用）
    return_context=True の場合は (theme, context) を返す。
    """
    ct = (content_type or "vocab").lower()
    if ct != "vocab":
        return ("general vocabulary", _context_for_theme("general vocabulary")) if return_context else "general vocabulary"

    # --- 強制指定（デバッグ用） ---
    forced_theme  = os.getenv("FORCE_THEME", "").strip()
    forced_bucket = os.getenv("FORCE_BUCKET", "").strip().lower()  # verb/collocation/acts/scene/grammar
    if forced_theme:
        return (forced_theme, _context_for_theme(forced_theme)) if return_context else forced_theme

    # --- 安定シード（言語ごと独立） ---
    today_seed = int(datetime.date.today().strftime("%Y%m%d")) + (hash(audio_lang) % 1000)
    rng = random.Random(today_seed)

    # --- CEFRレベルごとの重み ---
    level = os.getenv("CEFR_LEVEL", "A2").upper()
    if level == "A1":
        weights = {
            "scene": 6, "acts": 5, "collocation": 2, "verb": 2, "grammar": 5, "top": 5
        }
    elif level == "B1":
        weights = {
            "scene": 3, "acts": 5, "collocation": 6, "verb": 6, "grammar": 4, "top": 7
        }
    else:  # A2 default
        weights = {
            "scene": 5, "acts": 5, "collocation": 4, "verb": 4, "grammar": 5, "top": 6
        }

    # --- バケット構築 ---
    bucket_map = {
        "verb": THEMES_VERB_CLUSTERS,
        "collocation": THEMES_COLLOCATIONS,
        "acts": THEMES_COMMUNICATION_ACTS,
        "scene": THEMES_SCENE,
        "grammar": THEMES_GRAMMAR_FUNCTIONS,
        "top": TOP_PRIORITY,
    }

    # 強制バケット（任意）
    if forced_bucket in bucket_map:
        pool = bucket_map[forced_bucket][:]
    else:
        pool = []
        for key, items in bucket_map.items():
            pool += items * max(1, int(weights.get(key, 1)))

    # 日替わり一様選択（重み適用後のプールから）
    theme = rng.choice(pool)

    if return_context:
        return theme, _context_for_theme(theme)
    return theme

# ---- ローカルテスト ----
if __name__ == "__main__":
    print(pick_by_content_type("vocab", "en"))
    print(pick_by_content_type("vocab", "en", return_context=True))