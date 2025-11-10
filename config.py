# config.py  – 2 スピーカー用ボイスを全言語で分離
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# ── ディレクトリ ───────────────────────────────
BASE   = Path(__file__).parent
INPUT  = BASE / "input"
OUTPUT = BASE / "output"
TEMP   = BASE / "temp"
for d in (INPUT, OUTPUT, TEMP): d.mkdir(exist_ok=True)

# ── API キー ──────────────────────────────────
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")

# ── OpenAI TTS 用 (Alice 用, Bob 用) ───────────
VOICE_MAP = {
    "en": ("alloy", "echo"),       # 英語
    "ja": ("nova", "echo"),        # 日本語（Google TTS優先なので未使用）
    "es": ("fable", "onyx"),       # ★ スペイン語：明るめ女性 / 落ち着いた男性
    "id": ("alloy", "fable"),      # インドネシア語
    "ko": ("alloy", "echo"),       # 韓国語
}
# 必要に応じてボイス名は自由に差し替えてください
