# hook.py – テーマに応じた冒頭フックを音声言語で生成

import re
from typing import Optional
from translate import translate  # ★ 追加：既存の翻訳関数を利用

# 今回の音声言語は en / ja / ko / pt をサポート
_SUPPORTED = {"en", "ja", "ko", "pt"}

# 言語別テンプレ（疑問→共感→ベネフィット）
TPL = {
    "en": [
        "Ever struggled with {mini}? Let's fix it in 60 seconds.",
        "Do you know the easiest way to {mini}? Watch this.",
        "If {scene} makes you nervous, these phrases will help.",
        "Real phrases for {mini}—clear, polite, and quick.",
    ],
    "ja": [
        "{mini}で困ったこと、ありませんか？ 60秒で要点だけ。",
        "{mini}を一番かんたんに言うなら？ これです。",
        "{scene}で迷わないための実用フレーズだけ。",
        "ていねいに、短く、伝わる。{mini}の言い方を押さえよう。",
    ],
    "ko": [
        "{mini}가 어렵게 느껴졌나요? 60초로 정리합니다.",
        "{mini}를 가장 쉽게 말하는 방법, 지금 보여드릴게요.",
        "{scene}에서 바로 쓰는 실전 표현만 모았습니다.",
        "정중하고 간단하게 전하는 {mini} 핵심 표현.",
    ],
    "pt": [
        "Já teve dificuldade com {mini}? Vamos resolver em 60 segundos.",
        "Qual é a forma mais fácil de {mini}? É esta.",
        "Frases reais para {scene}: educadas e diretas.",
        "{mini} sem nervosismo — expressões curtas e claras.",
    ],
}

def _maybe_translate(text: str, lang: str) -> str:
    """英字が残っている場合のみ、既存の translate() で目標言語へ翻訳"""
    if not text:
        return text
    if lang != "en" and re.search(r"[A-Za-z]", text):
        try:
            out = (translate(text, lang) or "").strip()
            return out or text
        except Exception:
            return text
    return text

def _parse_theme(theme: str) -> tuple[str, str]:
    """
    "functional – scene" 形式を想定（en dash/ハイフン両対応）。
    例: "polite requests – restaurant ordering"
    """
    if not theme:
        return ("everyday phrases", "a simple situation")
    parts = [p.strip() for p in re.split(r"[–-]", theme, maxsplit=1)]
    if len(parts) == 2:
        functional, scene = parts[0], parts[1]
    else:
        functional, scene = parts[0], ""
    def trim(x: str) -> str:
        x = x.replace("&", "and")
        x = re.sub(r"\s+", " ", x)
        return x.strip().lower()
    return (trim(functional), trim(scene) or "a simple situation")

def _mini(functional: str, scene: str, lang: str) -> tuple[str, str]:
    """
    画面で読ませやすい短縮説明（mini）と scene 表示用ラベルを返す
    （辞書で補えない＝英語が残った場合は _maybe_translate で確実にローカライズ）
    """
    mapping_en = {
        "polite requests": "polite requests",
        "asking and giving directions": "asking for directions",
        "numbers and prices": "numbers and prices",
        "time and dates": "time and dates",
        "job interviews": "job interview answers",
        "restaurant ordering": "ordering at a restaurant",
        "shopping basics": "shopping",
        "paying and receipts": "paying and receipts",
        "hotel check-in/out": "hotel check-in",
        "street directions": "asking for directions",
    }
    f_en = mapping_en.get(functional, functional)
    s_en = mapping_en.get(scene, scene)

    if lang == "ja":
        f = {
            "polite requests": "ていねいなお願い",
            "asking and giving directions": "道の聞き方",
            "numbers and prices": "数・値段の言い方",
            "time and dates": "時間・日付の言い方",
            "job interviews": "面接の答え方",
        }.get(functional, functional)
        s = {
            "restaurant ordering": "レストラン注文",
            "shopping basics": "買い物",
            "paying and receipts": "支払い・レシート",
            "hotel check-in": "ホテルのチェックイン",
            "asking for directions": "道の聞き方",
        }.get(s_en, s_en)

        # ★ 英字が残っていたら翻訳でクリーンアップ
        f = _maybe_translate(f, lang)
        s = _maybe_translate(s, lang)

        mini = f if len(f) <= len(s) else s
        return mini or "実用フレーズ", s or "場面"

    if lang == "ko":
        f = {
            "polite requests": "공손한 부탁",
            "asking and giving directions": "길 묻기",
            "numbers and prices": "숫자와 가격",
            "time and dates": "시간과 날짜",
            "job interviews": "면접 답변",
        }.get(functional, functional)
        s = {
            "restaurant ordering": "식당 주문",
            "shopping basics": "쇼핑",
            "paying and receipts": "결제와 영수증",
            "hotel check-in": "호텔 체크인",
            "asking for directions": "길 묻기",
        }.get(s_en, s_en)

        # ★ 英字が残っていたら翻訳
        f = _maybe_translate(f, lang)
        s = _maybe_translate(s, lang)

        mini = f if len(f) <= len(s) else s
        return mini or "실용 표현", s or "상황"

    if lang == "pt":
        f = {
            "polite requests": "pedidos educados",
            "asking and giving directions": "pedir direções",
            "numbers and prices": "números e preços",
            "time and dates": "hora e datas",
            "job interviews": "respostas de entrevista",
        }.get(functional, functional)
        s = {
            "restaurant ordering": "pedido no restaurante",
            "shopping basics": "compras",
            "paying and receipts": "pagamento e recibos",
            "hotel check-in": "check-in no hotel",
            "asking for directions": "pedir direções",
        }.get(s_en, s_en)

        # ★ 英字が残っていたら翻訳
        f = _maybe_translate(f, lang)
        s = _maybe_translate(s, lang)

        mini = f if len(f) <= len(s) else s
        return mini or "frases úteis", s or "situação"

    # default en（英語はそのまま）
    mini = f_en if len(f_en) <= len(s_en) else s_en
    return mini or "everyday phrases", s_en or "a simple situation"

def generate_hook(theme: str, audio_lang: str, pattern_hint: Optional[str] = None) -> str:
    """
    1) theme → functional/scene を抽出
    2) 言語別テンプレを選択
    3) {mini}/{scene} を差し込み
    4) 文字数を ~90字（ja/ko）/~85 chars（en/pt）に収める
    """
    lang = (audio_lang or "en").lower()
    if lang not in _SUPPORTED:
        lang = "en"

    f, s = _parse_theme(theme)
    mini, scene_label = _mini(f, s, lang)

    # pattern に応じた軽微なテンプレ順序入れ替え
    tone_key = None
    if pattern_hint:
        p = pattern_hint.lower()
        if "polite" in p or "request" in p:
            tone_key = "polite"
        elif "direction" in p or "route" in p:
            tone_key = "directions"
        elif "confirm" in p:
            tone_key = "confirm"

    tpls = TPL[lang][:]
    if tone_key == "polite":
        tpls = [tpls[0], tpls[3], tpls[1], tpls[2]]
    elif tone_key == "directions":
        tpls = [tpls[1], tpls[2], tpls[0], tpls[3]]
    elif tone_key == "confirm":
        tpls = [tpls[2], tpls[0], tpls[1], tpls[3]]

    text = tpls[0].format(mini=mini, scene=scene_label)

    limit = 90 if lang in {"ja", "ko"} else 85
    if len(text) > limit:
        text = text[:limit - 1].rstrip(" .、。!？?!") + "…"

    return text