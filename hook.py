# hook.py – YouTube Shorts最適化・決定版（main.py互換）
# 目的:
#  - 0.5〜1.2秒で「自己投影」させる強フック（Shock/Empathy/Time/Release/Status）
#  - theme = "functional – scene" から {mini}/{scene} を自動抽出
#  - pattern_hint（Could I / Do you have… 等）に応じて最適テンプレを自動選択
#  - 言語: en / ja / ko / pt をネイティブ自然文で生成（記号やスラッシュ多用を回避）
#  - 長さ制御: 英語系85字、日本語/韓国語90字（ENVで変更可）
#
# 使い方（既存のまま）:
#   from hook import generate_hook
#   text = generate_hook(theme, audio_lang, pattern_hint)
#
# 推奨ENV（任意）:
#   HOOK_AB=0..4         # 固定カテゴリA/B（未指定なら自動選択）
#   HOOK_MAX_CHARS=85    # 英語系の最大文字数（ja/koは+5）
#
# 字幕側は main.py で hook 行のみ 2文まで許可済み（_clean_sub_line_hook）。
# ここでは 1〜2文の短文のみ返します。

import os
import re
import random
from typing import Optional, Tuple

# ---------------- ユーティリティ ----------------

def _limit(text: str, lang: str) -> str:
    try:
        max_en = int(os.getenv("HOOK_MAX_CHARS", "85"))
    except Exception:
        max_en = 85
    limit = max_en if lang in ("en", "pt") else max_en + 5  # ja/ko やや長めOK
    if len(text) <= limit:
        return text
    t = text[:limit].rstrip(" .、。!？?!")
    return t + "…"

def _normalize_spaces(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    # 日本語まわりは全角記号の周辺を軽く整形
    s = s.replace(" ，", "，").replace(" 。", "。").replace(" ！", "！").replace(" ？", "？")
    return s

def _parse_theme(theme: str) -> Tuple[str, str]:
    """ 'functional – scene' 形式から functional/scene を抽出。どちらか欠けたら補完。 """
    if not theme:
        return ("everyday phrases", "a simple situation")
    parts = [p.strip() for p in re.split(r"[–\-—]", theme, maxsplit=1)]
    if len(parts) == 2:
        functional, scene = parts[0], parts[1]
    else:
        functional, scene = parts[0], "a simple situation"
    return (functional or "everyday phrases", scene or "a simple situation")

def _mini_and_scene_label(functional: str, scene: str, lang: str) -> Tuple[str, str]:
    """ 画面に載せやすい短い {mini} と {scene} ラベル（言語別） """
    # 英語の素朴な基準ラベル
    base_map_en = {
        "polite requests": "polite requests",
        "asking & giving directions": "asking for directions",
        "numbers & prices": "numbers and prices",
        "time & dates": "time and dates",
        "job interviews": "job interview answers",
        "restaurant ordering": "ordering at a restaurant",
        "shopping basics": "shopping",
        "paying & receipts": "paying and receipts",
        "hotel check-in/out": "hotel check-in",
        "street directions": "asking for directions",
    }
    f_en = base_map_en.get(functional.lower(), functional)
    s_en = base_map_en.get(scene.lower(), scene)

    if lang == "ja":
        f = {
            "polite requests": "ていねいなお願い",
            "asking and giving directions": "道の聞き方",
            "numbers and prices": "数・値段の言い方",
            "time and dates": "時間・日付の言い方",
            "job interviews": "面接の答え方",
        }.get(functional.lower(), functional)
        s = {
            "ordering at a restaurant": "レストラン注文",
            "shopping": "買い物",
            "paying and receipts": "支払い・レシート",
            "hotel check-in": "ホテルのチェックイン",
            "asking for directions": "道の聞き方",
        }.get(s_en.lower(), scene)
        mini = f if len(f) <= len(s) else s
        return (_normalize_spaces(mini or "実用フレーズ"), _normalize_spaces(s or "この場面"))

    if lang == "ko":
        f = {
            "polite requests": "공손한 부탁",
            "asking and giving directions": "길 묻기",
            "numbers and prices": "숫자와 가격",
            "time and dates": "시간과 날짜",
            "job interviews": "면접 답변",
        }.get(functional.lower(), functional)
        s = {
            "ordering at a restaurant": "식당 주문",
            "shopping": "쇼핑",
            "paying and receipts": "결제와 영수증",
            "hotel check-in": "호텔 체크인",
            "asking for directions": "길 묻기",
        }.get(s_en.lower(), scene)
        mini = f if len(f) <= len(s) else s
        return (_normalize_spaces(mini or "실용 표현"), _normalize_spaces(s or "이 상황"))

    if lang == "pt":
        f = {
            "polite requests": "pedidos educados",
            "asking and giving directions": "pedir direções",
            "numbers and prices": "números e preços",
            "time and dates": "hora e datas",
            "job interviews": "respostas de entrevista",
        }.get(functional.lower(), functional)
        s = {
            "ordering at a restaurant": "pedido no restaurante",
            "shopping": "compras",
            "paying and receipts": "pagamento e recibos",
            "hotel check-in": "check-in no hotel",
            "asking for directions": "pedir direções",
        }.get(s_en.lower(), scene)
        mini = f if len(f) <= len(s) else s
        return (_normalize_spaces(mini or "frases úteis"), _normalize_spaces(s or "esta situação"))

    # default: en
    mini = f_en if len(f_en) <= len(s_en) else s_en
    return (_normalize_spaces(mini or "everyday phrases"), _normalize_spaces(s_en or "this situation"))

# ---------------- テンプレ定義 ----------------

HOOKS = {
    "en": {
        "shock":   ["Never say this at {scene}.", "This sounds rude at {scene}."],
        "empathy": ["Ever freeze up at {scene}?", "Said this and got weird looks?"],
        "time":    ["30 seconds. Fix your {mini}.", "Learn {mini} in half a minute."],
        "release": ["Stop saying this. Try this.", "Tired of saying it wrong? Use this."],
        "status":  ["Say this to sound confident.", "One phrase to sound fluent at {scene}."],
        "confirm": ["Not sure what to say at {scene}? Use this."],
        "directions": ["Lost at {scene}? Say this.", "Don’t panic. Ask like this."],
    },
    "ja": {
        "shock":   ["{scene}でこれ言うと失礼です。", "{scene}でその言い方は伝わりません。"],
        "empathy": ["{scene}で固まったこと、ある？", "こう言って変な顔されたことない？"],
        "time":    ["30秒で{mini}を直そう。", "30秒で{scene}の言い方を覚える。"],
        "release": ["毎回同じ言い方してない？ これに変えよう。", "{mini}は、この一言で通じます。"],
        "status":  ["こう言えば自然でスマート。", "{scene}で自信を持てる一言。"],
        "confirm": ["{scene}で迷う？ まずはこれだけ。"],
        "directions": ["道に迷っても大丈夫。こう聞けばOK。"],
    },
    "ko": {
        "shock":   ["{scene}에서 이렇게 말하면 실례예요.", "{scene}에서 그 말은 잘 안 통해요."],
        "empathy": ["{scene}에서 말이 막힌 적 있죠?", "이렇게 말하고 어색했던 적 있어요?"],
        "time":    ["30초면 {mini} 정리 끝.", "30초에 {scene} 한마디 익히기."],
        "release": ["매번 같은 말만? 이 표현으로 바꿔요.", "{mini}, 이 한마디면 됩니다."],
        "status":  ["이렇게 말하면 자연스럽게 들려요.", "{scene}에서 자신 있게 말하는 한마디."],
        "confirm": ["{scene}에서 망설여지면, 이걸로 시작하세요."],
        "directions": ["길을 잃어도 괜찮아요. 이렇게 물어보면 돼요."],
    },
    "pt": {
        "shock":   ["Isso soa rude em {scene}.", "Nunca diga isso em {scene}."],
        "empathy": ["Travou em {scene}?", "Já falou e ficou estranho?"],
        "time":    ["30 segundos para arrumar {mini}.", "Aprenda {mini} em meio minuto."],
        "release": ["Pare de dizer assim. Fale assim.", "Cansou de errar? Use isto."],
        "status":  ["Diga assim e soe confiante.", "Uma frase para soar fluente em {scene}."],
        "confirm": ["Ficou na dúvida em {scene}? Use isto."],
        "directions": ["Perdido em {scene}? Pergunte assim."],
    },
}

# pattern_hint からカテゴリ優先度を決める
def _preferred_order_by_pattern(p: Optional[str]) -> Tuple[str, ...]:
    p = (p or "").lower()
    if any(k in p for k in ("direction", "route")):
        return ("directions", "empathy", "time", "status", "release", "shock", "confirm")
    if any(k in p for k in ("confirm", "availability", "detail")):
        return ("confirm", "time", "status", "release", "empathy", "shock", "directions")
    if any(k in p for k in ("could i", "would you", "may i", "polite")):
        return ("status", "time", "release", "empathy", "shock", "confirm", "directions")
    # 汎用
    return ("empathy", "time", "status", "release", "shock", "confirm", "directions")

def _pick_category(lang: str, pattern_hint: Optional[str]) -> str:
    # 明示A/B指定があれば固定
    ab = os.getenv("HOOK_AB", "").strip()
    cats = list(HOOKS[lang].keys())
    if ab.isdigit():
        return cats[int(ab) % len(cats)]
    # そうでなければ pattern_hint からの優先順
    for c in _preferred_order_by_pattern(pattern_hint):
        if c in HOOKS[lang]:
            return c
    return "empathy"

# ---------------- 公開API ----------------

def generate_hook(theme: str, audio_lang: str, pattern_hint: Optional[str] = None) -> str:
    """
    返り値: 1〜2文の短いフック（字幕側で2文まで許容済み）
    """
    lang = (audio_lang or "en").lower()
    if lang not in HOOKS:
        lang = "en"

    functional, scene = _parse_theme(theme)
    mini, scene_label = _mini_and_scene_label(functional, scene, lang)

    cat = _pick_category(lang, pattern_hint)
    template = random.choice(HOOKS[lang][cat])
    text = template.format(mini=mini, scene=scene_label)

    # 二文目の「行動指示」を短く自動追加（過度な記号は避ける）
    add_callout = {
        "en": "Watch and copy one line.",
        "ja": "この一言だけ覚えよう。",
        "ko": "이 한마디만 따라 하자.",
        "pt": "Veja e repita uma frase.",
    }
    # 文字数に余裕があれば2文目を付加（最大2文）
    with_callout = f"{text} {add_callout[lang]}"
    if len(with_callout) <= (int(os.getenv("HOOK_MAX_CHARS", "85")) + (0 if lang in ("en", "pt") else 5)):
        text = with_callout

    text = _normalize_spaces(text)
    text = _limit(text, lang)
    return text