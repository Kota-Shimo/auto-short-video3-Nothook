# ================= subtitle_video.py =================
from moviepy import (
    ImageClip, TextClip, AudioFileClip, ColorClip, concatenate_videoclips
)
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import os, unicodedata as ud, re, textwrap
from pathlib import Path

# ---------- Fonts ----------
FONT_DIR  = Path(__file__).parent / "fonts"
FONT_LATN = str(FONT_DIR / "RobotoSerif_36pt-Bold.ttf")
FONT_JP   = str(FONT_DIR / "NotoSansJP-Bold.ttf")
FONT_KO   = str(FONT_DIR / "malgunbd.ttf")
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

# ---------- Screen / Layout ----------
SCREEN_W, SCREEN_H = 1080, 1920
TEXT_W             = 880
POS_Y              = 920
BOTTOM_MARGIN      = 40
PAD_X, PAD_Y       = 22, 16

# ── X 位置ずらし用 ───────────────────────────────
SHIFT_X = -45
def xpos(w: int) -> int:
    return (SCREEN_W - w) // 2 + SHIFT_X
def xpos_center(w: int) -> int:
    return (SCREEN_W - w) // 2

# ---------- Typography (3段まで対応) ----------
# 上段（音声言語）
FONT_SIZE_TOP       = 50
CJK_WIDTH_TOP       = 16
# 中段（ふりがな：ja-kana / ja-Latn / ko-Latn を想定）
FONT_SIZE_FURI      = 42
CJK_WIDTH_FURI      = 20   # かな行の改行幅
# 下段（翻訳字幕）
FONT_SIZE_BOT       = 45
CJK_WIDTH_BOT       = 18

# 行間（帯と帯の間隔）
LINE_GAP_TOP_TO_FURI = 22
LINE_GAP_FURI_TO_BOT = 26
LINE_GAP_DEFAULT     = 28   # 2段時の従来値

# 色・縁取り
COLOR_TEXT      = "white"
STROKE_COLOR    = "black"
STROKE_WIDTH    = 4
BAND_OPACITY    = 0.55

# ---------- 折り返しユーティリティ ----------
_ASCII_RE = re.compile(r'^[\x20-\x7E]+$')   # 可視ASCIIのみ（日本語/韓国語を除外）

def wrap_cjk(text: str, width: int = 16) -> str:
    """日本語/漢字/かな主体の文を width 文字で手動改行"""
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text or ""):
        return "\n".join(textwrap.wrap(text, width, break_long_words=True))
    return text or ""

def _split_long_token(tok: str, limit: int) -> list[str]:
    """空白のない長い英字トークンをlimitで分割（ハイフン/スラッシュ優先）"""
    if len(tok) <= limit:
        return [tok]
    parts = re.split(r"([-/])", tok)  # 区切り文字も保持
    merged, cur = [], ""
    for p in parts:
        if p in "-/":
            cur += p
            continue
        if not p:
            continue
        while len(p) > 0:
            take = limit - len(cur)
            if take <= 0:
                merged.append(cur); cur = ""
                take = limit
            seg, p = p[:take], p[take:]
            cur += seg
            if len(cur) >= limit:
                merged.append(cur); cur = ""
    if cur:
        merged.append(cur)
    return merged

def wrap_ascii_hard(text: str, cols: int) -> str:
    """英字比率が高い行に対して、空白のない長語を cols で強制改行。"""
    toks = (text or "").split()
    fixed = []
    for t in toks:
        if len(t) > cols and _ASCII_RE.match(t):
            fixed.extend(_split_long_token(t, cols))
        else:
            fixed.append(t)
    return textwrap.fill(" ".join(fixed), width=cols, break_long_words=True, break_on_hyphens=True)

def _prep_line(text: str, font_size: int, cjk_width: int) -> str:
    """
    文字種に応じて改行整形して返す。
    - CJK主体 → wrap_cjk(width=cjk_width)
    - 英字主体（ローマ字/英語）→ wrap_ascii_hard(cols≈TEXT_W/(font_size*0.58))
    """
    t = (text or "").strip()
    if not t:
        return t
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", t):
        return wrap_cjk(t, width=cjk_width)
    # 文字幅の簡易近似: 1文字 ≒ 0.58 * font_size ピクセル（経験則）
    approx_char_per_line = max(8, int(TEXT_W / (font_size * 0.58)))
    return wrap_ascii_hard(t, cols=approx_char_per_line)

# ---------- 見た目部品 ----------
def _bg(txt: TextClip) -> ColorClip:
    return ColorClip((txt.w + PAD_X * 2, txt.h + PAD_Y * 2), (0, 0, 0)).with_opacity(BAND_OPACITY)

def _make_block_plain(render_text: str, font_pick_text: str, font_size: int, cjk_width: int, add_trailing_space: bool = False):
    """
    ラベル無しの段（ふりがな／翻訳など）用。
    - 折り返しは font_pick_text に基づいて行う（render_textにその結果を反映）
    - 末尾に微小スペースを入れて高さを安定化可能
    """
    body_wrapped = _prep_line(font_pick_text, font_size=font_size, cjk_width=cjk_width)
    text_final = (body_wrapped + ("\n " if add_trailing_space else ""))
    clip = TextClip(
        text=text_final,
        font=pick_font(body_wrapped),
        font_size=font_size,
        color=COLOR_TEXT,
        stroke_color=STROKE_COLOR,
        stroke_width=STROKE_WIDTH,
        method="caption",
        size=(TEXT_W, None),
    )
    return clip, _bg(clip)

# ---------- メイン ----------
def build_video(
    lines,
    bg_path,
    voice_mp3,
    out_mp4,
    rows: int = 2,
    # 可変フォントサイズ受け口（未指定なら上の定数を使用）
    fsize_top: int | None = None,
    fsize_furi: int | None = None,
    fsize_bot: int | None = None,
    # 互換フラグ
    hide_n_label: bool = True,
    monologue_center: bool = False
):
    """
    lines : [(speaker, row1_text, row2_text, ..., duration_sec), ...]
            行内テキスト数は rows と一致していること（1〜3を想定）
            例）rows=3 → (speaker, top, furigana, bottom, dur)
    rows  : 1=上段のみ / 2=上段+下段 / 3=上段+ふりがな+下段
    """
    bg_base = ImageClip(bg_path).resized((SCREEN_W, SCREEN_H))
    clips = []

    FS_TOP  = fsize_top  or FONT_SIZE_TOP
    FS_FURI = fsize_furi or FONT_SIZE_FURI
    FS_BOT  = fsize_bot  or FONT_SIZE_BOT

    # 行ごとの設定
    FONT_SIZES = [FS_TOP,  FS_FURI,  FS_BOT]
    CJK_WIDTHS = [CJK_WIDTH_TOP, CJK_WIDTH_FURI, CJK_WIDTH_BOT]
    LINE_GAPS  = [LINE_GAP_TOP_TO_FURI, LINE_GAP_FURI_TO_BOT]
    if rows == 2:
        LINE_GAPS[0] = LINE_GAP_DEFAULT

    for item in lines:
        speaker, *row_texts, dur = item
        assert len(row_texts) >= 1, "row_texts must have at least 1 entry"
        assert rows == len(row_texts), f"rows={rows} but got {len(row_texts)} row_texts"

        is_n = (speaker == "N")
        posf = xpos_center if (is_n and monologue_center) else xpos

        elem = []
        current_y = POS_Y
        total_block_h = 0

        # ---- 段ごとに配置 ----
        for i in range(rows):
            text_i = row_texts[i] or ""

            if i == 0:
                # 上段（ラベル考慮）。フォント判定・折り返しは本文に対して行う
                body0_wrapped = _prep_line(text_i, font_size=FS_TOP, cjk_width=CJK_WIDTH_TOP)
                render0 = body0_wrapped if (is_n and hide_n_label) else f"{speaker}: {body0_wrapped}"
                clip_i = TextClip(
                    text=render0,
                    font=pick_font(body0_wrapped),
                    font_size=FS_TOP,
                    color=COLOR_TEXT,
                    stroke_color=STROKE_COLOR,
                    stroke_width=STROKE_WIDTH,
                    method="caption",
                    size=(TEXT_W, None),
                )
                bg_i = _bg(clip_i)

            else:
                # 中段（ふりがな）・下段（翻訳）
                # ふりがな行は確実にラップさせるため、本文で折返し→描画
                clip_i, bg_i = _make_block_plain(
                    render_text=text_i,
                    font_pick_text=text_i,
                    font_size=FONT_SIZES[i],
                    cjk_width=CJK_WIDTHS[i],
                    add_trailing_space=True
                )

            # ---- 位置計算と配置 ----
            if i == 0:
                elem += [
                    bg_i  .with_position((posf(bg_i.w),  current_y - PAD_Y)),
                    clip_i.with_position((posf(clip_i.w), current_y)),
                ]
                block_h = bg_i.h
            else:
                gap = LINE_GAPS[i - 1]
                y_i = current_y + block_h + gap
                elem += [
                    bg_i  .with_position((posf(bg_i.w),  y_i - PAD_Y)),
                    clip_i.with_position((posf(clip_i.w), y_i)),
                ]
                block_h = (y_i - current_y) + bg_i.h

            total_block_h = (elem[-1].pos(0)[1] + bg_i.h + PAD_Y) - POS_Y

        # ---- 画面下はみ出し補正（全部を上へシフト）----
        overflow = POS_Y + total_block_h + BOTTOM_MARGIN - SCREEN_H
        if overflow > 0:
            elem = [c.with_position((c.pos(0)[0], c.pos(0)[1] - overflow)) for c in elem]

        comp = CompositeVideoClip([bg_base, *elem]).with_duration(dur)
        clips.append(comp)

    video = concatenate_videoclips(clips, method="compose").with_audio(AudioFileClip(voice_mp3))
    video.write_videofile(out_mp4, fps=30, codec="libx264", audio_codec="aac")
# =====================================================