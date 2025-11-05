# hook.py – YouTube Shorts最適化・決定版（main.py互換・視点自動推定版）
# 目的:
#  - 0.5〜1.2秒で「自己投影」させる強フック（Shock/Empathy/Time/Release/Status）
#  - theme から {mini}/{scene} を抽出し、さらに「誰→誰」の視点を自動推定
#  - pattern_hint（Could I / Do you have… 等）や視点で最適テンプレを自動選択
#  - 言語: en / ja / ko / pt（自然文・記号多用回避）
#  - 長さ制御: 英/葡=85字、日本/韓国=90字（ENVで変更可）
#
# 使い方（既存のまま）:
#   from hook import generate_hook
#   text = generate_hook(theme, audio_lang, pattern_hint)
#
# 追加オプション（任意）:
#   HOOK_AB=0..n           # テンプレカテゴリ固定（未指定なら自動）
#   HOOK_MAX_CHARS=85      # 英語系の最大文字数（ja/koは+5）
#   HOOK_SPEAKER/HOOK_LISTENER  # 明示的に視点を上書きしたい場合

import os
import re
import random
from typing import Optional, Tuple
from translate import translate  # ★ 各言語へ毎回きちんと翻訳

# ---------------- ユーティリティ ----------------

_ASCII_WORD_RE = re.compile(r"[A-Za-z]+")
_ASCII_SYMBOLS_RE = re.compile(r"[\/\-\→\(\)\[\]\<\>\|\_]+")
_ASCII_ONLY_RE = re.compile(r'^[\x00-\x7F]+$')

def _limit(text: str, lang: str) -> str:
    try:
        max_en = int(os.getenv("HOOK_MAX_CHARS", "85"))
    except Exception:
        max_en = 85
    limit = max_en if lang in ("en", "pt") else max_en + 5  # ja/ko は少し長めOK
    if len(text) <= limit:
        return text
    t = text[:limit].rstrip(" .、。!？?!")
    return t + "…"

def _normalize_spaces(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    # 全角記号まわりの軽整形
    s = s.replace(" ，", "，").replace(" 。", "。").replace(" ！", "！").replace(" ？", "？")
    return s

def _enforce_lang_clean(text: str, lang: str) -> str:
    """
    audio_lang への統一を徹底：
      - ja/ko では英字とASCII系の飾り記号を除去（数字は許容）
      - en/pt はそのまま（テンプレが多言語を含まない前提）
    """
    t = (text or "")
    if lang in ("ja", "ko"):
        t = _ASCII_WORD_RE.sub("", t)          # 英字の除去
        t = _ASCII_SYMBOLS_RE.sub(" ", t)      # ASCII記号の抑制
        t = t.replace("..", "。").replace("!!", "！").replace("??", "？")
        t = _normalize_spaces(t)
    else:
        t = _normalize_spaces(t)
    return t

def _parse_theme(theme: str) -> Tuple[str, str]:
    """ 'functional – scene' 形式から functional/scene を抽出。片方欠けたら補完。 """
    if not theme:
        return ("everyday phrases", "a simple situation")
    parts = [p.strip() for p in re.split(r"[–\-—]", theme, maxsplit=1)]
    if len(parts) == 2:
        functional, scene = parts[0], parts[1]
    else:
        functional, scene = parts[0], "a simple situation"
    return (functional or "everyday phrases", scene or "a simple situation")

def _mini_and_scene_label(functional: str, scene: str, lang: str) -> Tuple[str, str]:
    """
    画面に載せやすい短い {mini} と {scene} ラベル。
    ルール：
      1) 英語の表記ゆらぎを軽く正規化（英語ベースの意味合わせのみ）
      2) その後、対象言語 lang に **毎回 translate() で翻訳**（既に多言語なら尊重）
      3) 仕上げの軽整形
      4) 短い方を {mini}、もう一方を {scene}
    """
    # --- 1) 英語ゆらぎの正規化（英語の意味カテゴリ合わせ用。出力に英語は使わない） ---
    base_map_en = {
        "polite requests": "polite requests",
        "asking & giving directions": "asking for directions",
        "asking and giving directions": "asking for directions",
        "numbers & prices": "numbers and prices",
        "time & dates": "time and dates",
        "job interviews": "job interview answers",
        "restaurant ordering": "ordering at a restaurant",
        "shopping basics": "shopping",
        "paying & receipts": "paying and receipts",
        "hotel check-in/out": "hotel check-in",
        "street directions": "asking for directions",
        "ordering coffee at a cafe": "ordering at a cafe",
    }
    f_en = base_map_en.get((functional or "").strip().lower(), (functional or "everyday phrases"))
    s_en = base_map_en.get((scene or "").strip().lower(),      (scene      or "a simple situation"))

    # --- 2) 対象言語へ翻訳（英語 or ASCIIなら確実に訳す。既に多言語ならそのまま） ---
    def _localize(text_candidate: str, target_lang: str) -> str:
        tc = (text_candidate or "").strip()
        if not tc:
            return ""
        if target_lang == "en":
            # 英語ターゲット時：そのまま英語（ただし整形）
            return _normalize_spaces(tc)
        # ASCIIのみ＝英語等 → 訳す / 非ASCII＝既に多言語 → そのまま
        if _ASCII_ONLY_RE.fullmatch(tc):
            try:
                out = translate(tc, target_lang)
                out = _normalize_spaces(out.strip(" ・:：-—|｜"))
                return out
            except Exception:
                return _normalize_spaces(tc)
        else:
            return _normalize_spaces(tc)

    f_local = _localize(f_en, lang)
    s_local = _localize(s_en, lang)

    # --- 3) 軽い後処理（言語別の最小限整形） ---
    if lang in ("ja", "ko", "pt", "en"):
        f_local = _normalize_spaces(f_local)
        s_local = _normalize_spaces(s_local)

    # 空落ち保険
    if not f_local:
        f_local = _normalize_spaces(f_en)
    if not s_local:
        s_local = _normalize_spaces(s_en)

    # --- 4) 短い方を {mini}、もう一方を {scene} ---
    mini = f_local if len(f_local) <= len(s_local) else s_local
    return (mini or _normalize_spaces(f_local or "everyday phrases"),
            s_local or _normalize_spaces(s_en or "this situation"))

# ---------------- 視点（speaker→listener）自動推定 ----------------

_ROLE_MAP = {
    "restaurant": ("customer", "waiter"),
    "cafe": ("customer", "barista"),
    "hotel": ("guest", "receptionist"),
    "train": ("traveler", "station staff"),
    "station": ("traveler", "station staff"),
    "airport": ("traveler", "staff"),
    "shopping": ("customer", "clerk"),
    "store": ("customer", "clerk"),
    "pharmacy": ("customer", "pharmacist"),
    "doctor": ("patient", "receptionist"),
    "work": ("colleague", "colleague"),
    "gym": ("member", "trainer"),
    "direction": ("traveler", "local"),
    "ticket": ("traveler", "staff"),
    "check-in": ("guest", "receptionist"),
}

_REQUESTER_ROLES = {"customer","guest","traveler","patient","member","friend","colleague"}

def _infer_roles(theme: str, context: Optional[str]) -> Tuple[str, str]:
    # 明示上書き（ENV）
    sp_env = os.getenv("HOOK_SPEAKER", "").strip()
    ls_env = os.getenv("HOOK_LISTENER", "").strip()
    if sp_env and ls_env:
        return (sp_env, ls_env)

    text = f"{theme or ''} {context or ''}".lower()

    # コンテキストも含めてキーワード優先で推定
    for k, pair in _ROLE_MAP.items():
        if k in text:
            return pair

    # 追加の語感ヒント
    if any(x in text for x in ("reservation", "check in", "check-in", "front desk")):
        return ("guest", "receptionist")
    if any(x in text for x in ("order", "menu", "table")):
        return ("customer", "waiter")
    if any(x in text for x in ("latte", "americano", "barista")):
        return ("customer", "barista")

    # デフォルト
    return ("friend", "friend")

# ---------------- テンプレ定義（視点別に微調整） ----------------

HOOKS = {
    "en": {
        # requester（頼む側）向けは直接行動を促す
        "shock_req":   ["This sounds rude at {scene}.", "Never say this at {scene}."],
        "empathy_req": ["Freeze up at {scene}?", "Said it and got weird looks?"],
        "time_req":    ["30 seconds. Fix your {mini}.", "Half a minute to nail {scene}."],
        "release_req": ["Stop saying this. Say this instead.", "Tired of getting it wrong? Use this."],
        "status_req":  ["Say this to sound natural.", "One line to sound confident at {scene}."],
        "confirm_req": ["Not sure what to say at {scene}? Use this."],
        "direc_req":   ["Lost at {scene}? Ask like this."],

        # responder（受ける側）向けは案内系に寄せる
        "status_res":  ["Greet and guide smoothly at {scene}.", "Sound helpful in one line."],
        "time_res":    ["30 seconds to upgrade your greeting.", "Half a minute to guide naturally."],
        "release_res": ["Drop the stiff phrasing. Try this one.", "Make it clear and friendly."],
    },
    "ja": {
        "shock_req":   ["{scene}でその言い方は伝わりません。", "{scene}でそれは少し不自然です。"],
        "empathy_req": ["{scene}で固まったこと、ある？", "こう言って変な顔されたことない？"],
        "time_req":    ["30秒で{mini}を直そう。", "30秒で{scene}の言い方を覚える。"],
        "release_req": ["定型文ばかりになってない？ これに変えよう。", "{mini}は、この一言で通じる。"],
        "status_req":  ["こう言えば自然でスマート。", "{scene}で自信を持てる一言。"],
        "confirm_req": ["{scene}で迷う？ まずはこれだけ。"],
        "direc_req":   ["道に迷っても大丈夫。こう聞けばOK。"],

        "status_res":  ["{scene}で感じよく案内する一言。", "自然に案内できる言い方。"],
        "time_res":    ["30秒で案内の第一声を整える。", "半分の時間で丁寧に伝える。"],
        "release_res": ["堅い言い方は卒業。こう言えばスムーズ。", "回りくどさを減らして、これだけ。"],
    },
    "ko": {
        "shock_req":   ["{scene}에서 그 말은 잘 안 통해요.", "{scene}에서는 조금 어색해요."],
        "empathy_req": ["{scene}에서 말이 막힌 적 있죠?", "이렇게 말하고 어색했던 적 있어요?"],
        "time_req":    ["30초면 {mini} 정리 끝.", "30초에 {scene} 한마디 익히기."],
        "release_req": ["매번 같은 말만? 이 표현으로 바꿔요.", "{mini}, 이 한마디면 됩니다."],
        "status_req":  ["이렇게 말하면 자연스럽게 들려요.", "{scene}에서 자신 있게 말하는 한마디."],
        "confirm_req": ["{scene}에서 망설여지면, 이걸로 시작하세요."],
        "direc_req":   ["길을 잃어도 괜찮아요. 이렇게 물어보면 돼요."],

        "status_res":  ["{scene}에서 부드럽게 안내하는 한마디.", "친절하고 자연스럽게 전하는 방법."],
        "time_res":    ["30초면 첫마디가 달라집니다.", "반 분만에 자연스러운 안내."],
        "release_res": ["딱딱한 말투는 그만. 이렇게 말해요.", "돌려 말하지 말고, 이 한마디면 충분해요."],
    },
    "pt": {
        "shock_req":   ["Isso soa rude em {scene}.", "Não diga isso em {scene}."],
        "empathy_req": ["Travou em {scene}?", "Falou e ficou estranho?"],
        "time_req":    ["30 segundos para acertar {mini}.", "Meio minuto para {scene}."],
        "release_req": ["Pare de dizer assim. Diga assim.", "Cansou de errar? Use isto."],
        "status_req":  ["Diga assim para soar natural.", "Uma frase para soar confiante em {scene}."],
        "confirm_req": ["Ficou na dúvida em {scene}? Use isto."],
        "direc_req":   ["Perdido em {scene}? Pergunte assim."],

        "status_res":  ["Atenda bem com uma frase.", "Guie com naturalidade em {scene}."],
        "time_res":    ["30 segundos para melhorar sua abordagem.", "Meio minuto para receber melhor."],
        "release_res": ["Abandone o formalismo. Fale assim.", "Chega de rodeios. Diga isto."],
    },
}

def _preferred_order_by_pattern(p: Optional[str], requester: bool) -> Tuple[str, ...]:
    p = (p or "").lower()
    if any(k in p for k in ("direction", "route")):
        return (("direc_req","empathy_req","time_req","status_req","release_req","shock_req","confirm_req")
                if requester else ("status_res","time_res","release_res"))
    if any(k in p for k in ("confirm", "availability", "detail")):
        return (("confirm_req","time_req","status_req","release_req","empathy_req","shock_req","direc_req")
                if requester else ("status_res","time_res","release_res"))
    if any(k in p for k in ("could i", "would you", "may i", "polite")):
        return (("status_req","time_req","release_req","empathy_req","shock_req","confirm_req","direc_req")
                if requester else ("status_res","time_res","release_res"))
    # 汎用
    return (("empathy_req","time_req","status_req","release_req","shock_req","confirm_req","direc_req")
            if requester else ("status_res","time_res","release_res"))

def _pick_category(lang: str, pattern_hint: Optional[str], requester: bool) -> str:
    # 明示固定
    ab = os.getenv("HOOK_AB", "").strip()
    lang_keys = list(HOOKS[lang].keys())
    if ab.isdigit():
        return lang_keys[int(ab) % len(lang_keys)]
    # 優先順で最初に存在するキー
    for c in _preferred_order_by_pattern(pattern_hint, requester):
        if c in HOOKS[lang]:
            return c
    # フォールバック
    return "empathy_req" if requester else "status_res"

# ---------------- 公開API ----------------

def generate_hook(theme: str, audio_lang: str, pattern_hint: Optional[str] = None, context: Optional[str] = None) -> str:
    """
    返り値: 1〜2文の短いフック（字幕側で2文まで許容）
    ※ main.py から context=... が渡される前提で後方互換（第4引数は任意）
    """
    lang = (audio_lang or "en").lower()
    if lang not in HOOKS:
        lang = "en"

    functional, scene = _parse_theme(theme)
    mini, scene_label = _mini_and_scene_label(functional, scene, lang)

    speaker, listener = _infer_roles(theme, context)
    requester = speaker in _REQUESTER_ROLES

    cat = _pick_category(lang, pattern_hint, requester)
    template = random.choice(HOOKS[lang][cat])
    text = template.format(mini=mini, scene=scene_label)

    # 二文目の「行動指示」（“copy” は避け、自然な言い方に）
    add_callout = {
        "en": "Remember just this line.",
        "ja": "この一言だけ覚えよう。",
        "ko": "이 한마디만 외워 둬.",
        "pt": "Repita só esta frase.",
    }

    with_callout = f"{text} {add_callout[lang]}"
    max_lim = int(os.getenv("HOOK_MAX_CHARS", "85")) + (0 if lang in ("en","pt") else 5)
    if len(with_callout) <= max_lim:
        text = with_callout

    # 言語統一の強制クリーニング
    text = _enforce_lang_clean(text, lang)
    # 長さ最終制御
    text = _limit(text, lang)
    return text