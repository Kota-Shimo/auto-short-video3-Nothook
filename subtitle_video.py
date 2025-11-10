# ================= subtitle_video.py =================
from moviepy import (
    ImageClip, TextClip, AudioFileClip, ColorClip, concatenate_videoclips
)
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import os, unicodedata as ud, re, textwrap
from pathlib import Path

FONT_DIR  = Path(__file__).parent / "fonts"
FONT_LATN = str(FONT_DIR / "RobotoSerif_36pt-Bold.ttf")
FONT_JP   = str(FONT_DIR / "NotoSansJP-Bold.ttf")
FONT_KO   = str(FONT_DIR / "malgunbd.ttf")

# ── X 位置ずらし用 ───────────────────────────────
SHIFT_X = -45
def xpos(w: int) -> int:
    return (SCREEN_W - w) // 2 + SHIFT_X

# 中央寄せ用（モノローグ時のみ使用）
def xpos_center(w: int) -> int:
    return (SCREEN_W - w) // 2
# ────────────────────────────────────────────────

# ── CJK 折り返し ────────────────────────────────
def wrap_cjk(text: str, width: int = 16) -> str:
    """日本語や漢字のみの文を width 文字で手動改行"""
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
        return "\n".join(textwrap.wrap(text, width, break_long_words=True))
    return text
# ────────────────────────────────────────────────

for f in (FONT_LATN, FONT_JP, FONT_KO):
    if not os.path.isfile(f):
        raise FileNotFoundError(f"Font not found: {f}")

def pick_font(text: str) -> str:
    """文字種を見て適切なフォントパスを返す"""
    for ch in text:
        name = ud.name(ch, "")
        if "HANGUL" in name:
            return FONT_KO
        if any(tag in name for tag in ("CJK", "HIRAGANA", "KATAKANA")):
            return FONT_JP
    return FONT_LATN

# ===== レイアウト定数 =====
FONT_SIZE_TOP      = 50   # 上段（音声言語）
FONT_SIZE_BOT      = 45   # 下段（翻訳字幕）
LINE_GAP           = 28
POS_Y              = 920
TEXT_W             = 880
SCREEN_W, SCREEN_H = 1080, 1920
BOTTOM_MARGIN      = 40
PAD_X, PAD_Y       = 22, 16
# ===========================

# ── 半透明黒帯 ──────────────────────────────────
def _bg(txt: TextClip) -> ColorClip:
    return (
        ColorClip((txt.w + PAD_X * 2, txt.h + PAD_Y * 2), (0, 0, 0))
        .with_opacity(0.55)
    )
# ────────────────────────────────────────────────

# 追加: ラテン文字（ローマ字）判定と幅フィット
_LATN_RE = re.compile(r'^[\x20-\x7E]+$')  # ASCII 可視文字
def _is_latin_line(text: str) -> bool:
    t = (text or "").strip()
    return bool(_LATN_RE.fullmatch(t)) and any(c.isalpha() for c in t)

def _make_text_clip_fitted(
    text: str,
    base_size: int,
    is_latin: bool,
    with_label: bool,
):
    """
    - 通常は base_size をそのまま使う
    - ローマ字行のみ、TEXT_W を超える場合に限り 2px 刻みで最小限縮小
    """
    font_path = pick_font(text if not with_label else text.split(": ", 1)[-1])
    size = base_size
    min_size = max(36, base_size - 20) if is_latin else base_size  # ラテンのみ縮小許可

    # 一度作ってサイズ判定（caption は size=(TEXT_W,None) で横幅制限されるが、
    # stroke 等でパネル幅が伸びるケースがあるので txt.w を実測）
    def _build(sz: int) -> TextClip:
        return TextClip(
            text=text,
            font=font_path,
            font_size=sz,
            color="white", stroke_color="black", stroke_width=4,
            method="caption", size=(TEXT_W, None),
        )

    clip = _build(size)
    if not is_latin:
        return clip  # CJK は手動指定優先・縮小なし

    # ラテンのみ、枠超え時だけ縮小
    while clip.w > TEXT_W and size > min_size:
        size -= 2
        clip = _build(size)
    return clip

def _extract_cols(row, rows: int):
    """
    row: [speaker, col1, col2, ..., dur]
    rows の数だけ列テキストを返す（不足分は空文字）
    """
    out = []
    for j in range(rows):
        idx = 1 + j
        out.append(row[idx] if idx < len(row) - 1 else "")
    return out

def build_video(
    lines,
    bg_path,
    voice_mp3,
    out_mp4,
    rows: int = 2,
    # ▼ 受け口（手動指定は最優先）
    fsize_top=None,
    fsize_bot=None,
    hide_n_label: bool = True,
    monologue_center: bool = False
):
    """
    lines : [(speaker, col1, col2, ..., duration_sec), ...]
    rows  : 描画段数（例: 3 → col1/col2/col3 を描画）
    hide_n_label    : True のとき N のラベルを表示しない
    monologue_center: True のとき N の本文ブロックを中央寄せ配置
    """
    bg_base = ImageClip(bg_path).resized((SCREEN_W, SCREEN_H))
    clips = []

    # フォントサイズ（指定があれば優先）
    FS_TOP = fsize_top or FONT_SIZE_TOP
    FS_BOT = fsize_bot or FONT_SIZE_BOT

    for row in lines:
        speaker, *rest = row
        dur = rest[-1] if len(rest) >= 1 else 1.0
        is_n = (speaker == "N")
        posf = xpos_center if (is_n and monologue_center) else xpos

        cols = _extract_cols(row, rows)

        # 段ごとの描画要素を積む
        elem = []
        acc_h = 0  # ブロック総高さ

        for idx, text_body in enumerate(cols):
            if not text_body:
                continue

            # 1段目＝上段サイズ／2段目以降＝下段サイズ
            base_fs = FS_TOP if idx == 0 else FS_BOT

            # CJK は手動改行で読みやすさを確保
            body = wrap_cjk(text_body) if not _is_latin_line(text_body) else text_body

            # 上段のみラベル付与（N かつ hide_n_label=True の場合は非表示）
            with_label = (idx == 0) and not (is_n and hide_n_label)
            draw_text = f"{speaker}: {body}" if with_label else body

            # ローマ字行のみ、枠超え時に限って縮小
            is_latn = _is_latin_line(draw_text)
            clip = _make_text_clip_fitted(
                draw_text, base_fs, is_latn, with_label
            )
            bg = _bg(clip)

            # y 位置：先頭は POS_Y、以降は累積 + GAP
            y = POS_Y if acc_h == 0 else (POS_Y + acc_h + LINE_GAP)
            elem += [
                bg.with_position( (posf(bg.w),  y - PAD_Y) ),
                clip.with_position( (posf(clip.w), y) ),
            ]
            acc_h += (bg.h if acc_h == 0 else (LINE_GAP + bg.h))

        # はみ出し補正（全段まとめて上に押し上げる）
        overflow = POS_Y + acc_h + BOTTOM_MARGIN - SCREEN_H
        if overflow > 0:
            elem = [c.with_position((c.pos(0)[0], c.pos(0)[1] - overflow)) for c in elem]

        comp = CompositeVideoClip([bg_base, *elem]).with_duration(dur)
        clips.append(comp)

    video = concatenate_videoclips(clips, method="compose").with_audio(AudioFileClip(voice_mp3))
    video.write_videofile(out_mp4, fps=30, codec="libx264", audio_codec="aac")
# =====================================================