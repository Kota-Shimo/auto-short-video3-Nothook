#!/usr/bin/env python
"""
main.py – VOCAB専用版
単語テーマ（AUTO→topic_picker）→ 単語リスト生成 → [単語→訳（字幕）→例文] を繰り返し
→ TTS → lines.json & full.mp3 → chunk_builder.py で動画 → （任意）YouTubeアップロード

環境変数:
- VOCAB_WORDS        : 生成する語数 (既定: 6)
- VOCAB_SILENT_SECOND: "1" で各3行ブロックの2行目（=訳表示行）を無音にする(既定: 0)
"""

import argparse, logging, re, json, subprocess, os
from datetime import datetime
from pathlib import Path
from shutil import rmtree

import yaml
from pydub import AudioSegment
from openai import OpenAI

from config         import BASE, OUTPUT, TEMP
from translate      import translate
from tts_openai     import speak
from audio_fx       import enhance
from bg_image       import fetch as fetch_bg
from thumbnail      import make_thumbnail
from upload_youtube import upload
from topic_picker   import pick_by_content_type

# ───────────────────────────────────────────────
GPT = OpenAI()
MAX_SHORTS_SEC = 59.0

# 固定: vocab 専用
CONTENT_MODE = "vocab"

# ───────────────────────────────────────────────
# combos.yaml 読み込み
# ───────────────────────────────────────────────
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

def reset_temp():
    if TEMP.exists():
        rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

def sanitize_title(raw: str) -> str:
    import re
    title = re.sub(r"^\s*(?:\d+\s*[.)]|[-•・])\s*", "", raw)
    title = re.sub(r"[\s\u3000]+", " ", title).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Video"

LANG_NAME = {
    "en": "English", "pt": "Portuguese", "id": "Indonesian",
    "ja": "Japanese","ko": "Korean", "es": "Spanish",
}

# 日本語タイトル用のラベル（音声言語→◯◯語会話）
JP_CONV_LABEL = {
    "en": "英会話", "ja": "日本語会話", "es": "スペイン語会話",
    "pt": "ポルトガル語会話", "ko": "韓国語会話", "id": "インドネシア語会話",
}

# ───────────────────────────────────────────────
# トピック取得: "AUTO"→ vocab テーマを日替わりで選ぶ
# ───────────────────────────────────────────────
def resolve_topic(arg_topic: str) -> str:
    if arg_topic and arg_topic.strip().lower() == "auto":
        first_audio_lang = COMBOS[0]["audio"]
        topic = pick_by_content_type("vocab", first_audio_lang)  # ← vocabテーマ（英語ベースでOK）
        logging.info(f"[AUTO VOCAB THEME] {topic}")
        return topic
    return arg_topic

# ───────────────────────────────────────────────
# 語彙ユーティリティ
# ───────────────────────────────────────────────
def _gen_example_sentence(word: str, lang_code: str) -> str:
    """その単語を使った短い例文を1つだけ生成（失敗時はフォールバック）"""
    prompt = (
        f"Write one short, natural example sentence (<=12 words) in "
        f"{LANG_NAME.get(lang_code,'English')} using the word: {word}. "
        "No translation, no quotes."
    )
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.6,
        )
        import re
        sent = (rsp.choices[0].message.content or "").strip()
        return re.sub(r'^[\"“”\'\s]+|[\"“”\'\s]+$', '', sent)
    except Exception:
        return f"Let's practice the word {word} in a short sentence."

def _gen_vocab_list(theme: str, lang_code: str, n: int) -> list[str]:
    """
    テーマから n 語の単語リストを生成。失敗時はフォールバック。
    """
    theme_for_prompt = translate(theme, lang_code) if lang_code != "en" else theme
    prompt = (
        f"List {n} essential single or hyphenated words for {theme_for_prompt} context "
        f"in {LANG_NAME.get(lang_code,'English')}. Return ONLY one word per line, no numbering."
    )
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.5,
        )
        words = [w.strip() for w in (rsp.choices[0].message.content or "").splitlines() if w.strip()]
        import re
        cleaned = []
        for w in words:
            w = re.sub(r"^\d+[\).]?\s*", "", w)
            if w and w not in cleaned:
                cleaned.append(w)
        if len(cleaned) >= n:
            return cleaned[:n]
    except Exception:
        pass
    fallback = ["check-in", "reservation", "checkout", "receipt", "elevator", "lobby", "upgrade"]
    return fallback[:n]

# ───────────────────────────────────────────────
# メタ生成
# ───────────────────────────────────────────────
def make_title(theme, title_lang: str, audio_lang_for_label: str | None = None):
    """テーマに合わせた短い学習向けタイトル"""
    if title_lang == "ja":
        base = f"{theme} で使える一言"
        label = JP_CONV_LABEL.get(audio_lang_for_label or "", "")
        t = f"{label} {base}" if label and label not in base else base
        return sanitize_title(t)[:28]
    else:
        t = f"{theme.capitalize()} vocab in one minute"
        return sanitize_title(t)[:55]

def make_desc(theme, title_lang: str):
    msg = {
        "ja": f"{theme} に必須の語彙を短時間でチェック。声に出して一緒に練習しよう！ #vocab #learning",
        "en": f"Quick practice for {theme} vocabulary. Repeat after the audio! #vocab #learning",
        "pt": f"Pratique rápido o vocabulário de {theme}. Repita em voz alta! #vocab #aprendizado",
        "es": f"Práctica rápida de vocabulario de {theme}. ¡Repite en voz alta! #vocab #aprendizaje",
        "ko": f"{theme} 어휘를 빠르게 연습하세요. 소리 내어 따라 말해요! #vocab #learning",
        "id": f"Latihan cepat kosakata {theme}. Ucapkan keras-keras! #vocab #belajar",
    }
    return msg.get(title_lang, msg["en"])

def make_tags(theme, audio_lang, subs, title_lang):
    tags = [
        theme, "vocabulary", "language learning", "speaking practice",
        "listening practice", "subtitles"
    ]
    for code in subs:
        if code in LANG_NAME:
            tags.append(f"{LANG_NAME[code]} subtitles")
    # 重複除去・上限
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); out.append(t)
    return out[:15]

# ───────────────────────────────────────────────
# 音声結合・トリム（行間に無音ギャップを持たせ、dur にも反映）
# ───────────────────────────────────────────────
def _concat_trim_to(mp_paths, max_sec, gap_ms=120):
    max_ms = int(max_sec * 1000)
    combined = AudioSegment.silent(duration=0)
    new_durs, elapsed = [], 0

    for idx, p in enumerate(mp_paths):
        seg = AudioSegment.from_file(p)
        seg_ms = len(seg)
        extra = gap_ms if idx < len(mp_paths) - 1 else 0
        need = seg_ms + extra

        remain = max_ms - elapsed
        if remain <= 0:
            break

        if need <= remain:
            combined += seg
            elapsed += seg_ms
            if extra:
                combined += AudioSegment.silent(duration=extra)
                elapsed += extra
            new_durs.append((seg_ms + extra) / 1000.0)
        else:
            if remain <= seg_ms:
                combined += seg[:remain]
                new_durs.append(remain / 1000.0)
                elapsed += remain
            else:
                used_gap = remain - seg_ms
                combined += seg
                if used_gap > 0:
                    combined += AudioSegment.silent(duration=used_gap)
                new_durs.append((seg_ms + used_gap) / 1000.0)
                elapsed += seg_ms + used_gap
            break

    (TEMP / "full_raw.mp3").unlink(missing_ok=True)
    combined.export(TEMP / "full_raw.mp3", format="mp3")
    return new_durs

# ───────────────────────────────────────────────
# 1コンボ処理（vocab 専用）
# ───────────────────────────────────────────────
def run_one(topic, turns, audio_lang, subs, title_lang, yt_privacy, account, do_upload, chunk_size):
    reset_temp()

    # topic が「単語の列」ならそのまま使う。そうでなければ “テーマ” とみなして単語生成。
    raw = (topic or "").replace("\r", "\n").strip()
    is_word_list = bool(re.search(r"[,;\n]", raw)) and len([w for w in re.split(r"[\n,;]+", raw) if w.strip()]) >= 2

    words_count = int(os.getenv("VOCAB_WORDS", "6"))
    if is_word_list:
        vocab_words = [w.strip() for w in re.split(r"[\n,;]+", raw) if w.strip()]
        theme = "custom list"
    else:
        theme = topic
        vocab_words = _gen_vocab_list(theme, audio_lang, words_count)

    # 1語あたり 3行ブロック: ①単語 → ②単語（訳字幕に出す）→ ③例文
    dialogue = []
    for w in vocab_words:
        ex = _gen_example_sentence(w, audio_lang)
        dialogue.extend([("N", w), ("N", w), ("N", ex)])

    # 音声＆字幕
    valid_dialogue = [(spk, line) for (spk, line) in dialogue if line.strip()]
    mp_parts, sub_rows = [], [[] for _ in subs]
    for i, (spk, line) in enumerate(valid_dialogue, 1):
        mp = TEMP / f"{i:02d}.mp3"
        # 2行目（各ブロックの訳表示行）だけ無音にするオプション
        if os.getenv("VOCAB_SILENT_SECOND","0") == "1" and (i % 3 == 2):
            AudioSegment.silent(duration=900).export(mp, format="mp3")
        else:
            speak(audio_lang, spk, line, mp, style="neutral")
        mp_parts.append(mp)
        # 字幕を各言語で準備（音声言語=原文、それ以外は翻訳）
        for r, lang in enumerate(subs):
            sub_rows[r].append(line if lang == audio_lang else translate(line, lang))

    # 結合・整音
    new_durs = _concat_trim_to(mp_parts, MAX_SHORTS_SEC, gap_ms=120)
    enhance(TEMP/"full_raw.mp3", TEMP/"full.mp3")

    # 背景：最初の単語を使う
    bg_png = TEMP / "bg.png"
    first_word = valid_dialogue[0][1] if valid_dialogue else theme
    fetch_bg(first_word, bg_png)

    # 台本行数とオーディオ尺の整合
    valid_dialogue = valid_dialogue[:len(new_durs)]

    # lines.json 生成（[spk, sub1, sub2, ..., dur]）
    lines_data = []
    for i, ((spk, txt), dur) in enumerate(zip(valid_dialogue, new_durs)):
        row = [spk]
        for r in range(len(subs)):
            row.append(sub_rows[r][i])
        row.append(dur)
        lines_data.append(row)
    (TEMP/"lines.json").write_text(json.dumps(lines_data, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.lines_only:
        return

    # サムネ（タイトル言語はサブ2列目があればそれを優先）
    thumb = TEMP / "thumbnail.jpg"
    thumb_lang = subs[1] if len(subs) > 1 else audio_lang
    make_thumbnail(theme, thumb_lang, thumb)

    # 動画生成
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_mp4 = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    final_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python", str(BASE/"chunk_builder.py"),
        str(TEMP/"lines.json"), str(TEMP/"full.mp3"), str(bg_png),
        "--chunk", str(chunk_size),
        "--rows", str(len(subs)),
        "--out", str(final_mp4),
    ]
    logging.info("🔹 chunk_builder cmd: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

    if not do_upload:
        return

    # メタ生成＆アップロード
    title = make_title(theme, title_lang, audio_lang_for_label=audio_lang)
    desc  = make_desc(theme, title_lang)
    tags  = make_tags(theme, audio_lang, subs, title_lang)

    upload(video_path=final_mp4, title=title, desc=desc, tags=tags,
           privacy=yt_privacy, account=account, thumbnail=thumb, default_lang=audio_lang)

# ───────────────────────────────────────────────
def run_all(topic, turns, privacy, do_upload, chunk_size):
    for combo in COMBOS:
        audio_lang  = combo["audio"]
        subs        = combo["subs"]
        account     = combo.get("account","default")
        title_lang  = combo.get("title_lang", subs[1] if len(subs)>1 else audio_lang)
        logging.info(f"=== Combo: {audio_lang}, subs={subs}, account={account}, title_lang={title_lang}, mode={CONTENT_MODE} ===")

        # AUTO の場合: 言語ごとに vocab テーマを日替わりピック
        picked_topic = topic
        if topic.strip().lower() == "auto":
            picked_topic = pick_by_content_type("vocab", audio_lang)
            logging.info(f"[{audio_lang}] picked vocab theme: {picked_topic}")

        run_one(picked_topic, turns, audio_lang, subs, title_lang, privacy, account, do_upload, chunk_size)

# ───────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help='語彙テーマ。AUTO で自動選択。カンマ/改行区切りなら単語リストとして使用')
    ap.add_argument("--turns", type=int, default=8)  # 未使用（互換用）
    ap.add_argument("--privacy", default="unlisted", choices=["public","unlisted","private"])
    ap.add_argument("--lines-only", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--chunk", type=int, default=9999, help="Shortsは分割せず1本推奨")
    args = ap.parse_args()

    topic = resolve_topic(args.topic)
    run_all(topic, args.turns, args.privacy, not args.no_upload, args.chunk)