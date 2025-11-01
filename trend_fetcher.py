"""
学習言語ごとのトレンド候補を取得して、学習向きの短い“テーマ語”に正規化して返す。
- ソース: Google News RSS（国・言語別）/ Wikipedia Pageviews（昨日の急上昇）
- フォールバックなし（取得失敗時は例外をraise）
- 依存: 標準ライブラリのみ（APIキー不要）
- キャッシュ: 60分（TEMPフォルダに保存）
"""

from __future__ import annotations
import json, re, time, random, datetime as dt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET

# ──────────────────────────────────────────────
# 言語別設定
# ──────────────────────────────────────────────
NEWS_PARAMS = {
    "ja": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
    "en": {"hl": "en", "gl": "US", "ceid": "US:en"},
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
    "fr": {"hl": "fr", "gl": "FR", "ceid": "FR:fr"},
    "es": {"hl": "es", "gl": "ES", "ceid": "ES:es"},
    "pt": {"hl": "pt", "gl": "BR", "ceid": "BR:pt"},
    "id": {"hl": "id", "gl": "ID", "ceid": "ID:id"},
}

WIKI_PROJECT = {
    "ja": "ja.wikipedia",
    "en": "en.wikipedia",
    "ko": "ko.wikipedia",
    "fr": "fr.wikipedia",
    "es": "es.wikipedia",
    "pt": "pt.wikipedia",
    "id": "id.wikipedia",
}

# ──────────────────────────────────────────────
# 正規化ユーティリティ
# ──────────────────────────────────────────────
_CJK = r"\u4e00-\u9fff\u3040-\u30ff\u3400-\u4dbf"
_LAT = r"A-Za-zÀ-ÖØ-öø-ÿ"
_PUNCT = r"\u3000\s\-\–\—\:\;\,\.\!\?\(\)\[\]\{\}\'\"\“\”\‘\’\/\|#&$%+~*_＝=·•・"

RE_TAG = re.compile(r"<[^>]+>")
RE_SPACE = re.compile(r"\s+")
RE_BRACKETS = re.compile(r"[\(\（][^)）]{0,80}[\)\）]")
RE_URL = re.compile(r"https?://\S+")
RE_NUMBER = re.compile(r"\b\d{2,4}(?:\.\d+)?\b")
RE_END_PUNCT = re.compile(rf"[{_PUNCT}]+$")

STOPWORDS = {
    "ja": {"速報", "新型", "詳報", "特集", "写真", "動画"},
    "en": {"update", "breaking", "opinion", "analysis"},
    "ko": {"속보", "분석", "사설"},
    "fr": {"analyse", "opinion", "vidéo"},
    "es": {"análisis", "opinión", "video"},
    "pt": {"análise", "opinião", "vídeo"},
    "id": {"analisis", "opini", "video"},
}

def _clean_title(t: str) -> str:
    t = RE_TAG.sub("", t or "")
    t = RE_URL.sub("", t)
    t = RE_BRACKETS.sub("", t)
    t = RE_NUMBER.sub("", t)
    t = RE_SPACE.sub(" ", t).strip()
    t = RE_END_PUNCT.sub("", t)
    return t.strip()

def _is_good_len(s: str, lang: str) -> bool:
    if lang in ("ja", "ko"):
        return 2 <= len(s) <= 28
    words = re.findall(rf"[{_LAT}]+", s)
    return 1 <= len(words) <= 4 and 2 <= len(s) <= 40

def _looks_term_like(s: str, lang: str) -> bool:
    if not s: return False
    if not re.search(rf"[{_CJK}{_LAT}]", s): return False
    bad_suffix = ["ニュース", "通信", "日報", "タイムズ"]
    if lang == "ja" and any(s.endswith(x) for x in bad_suffix): return False
    lowers = set(re.findall(r"[a-z]+", s.lower()))
    if lowers and lowers.issubset(STOPWORDS.get(lang, set())): return False
    s2 = re.split(r"\s[:-]\s", s)[0].strip()
    # 一般語すぎるテーマの除外
    generic_words = {"restaurant", "news", "update", "event", "sports", "music", "fashion", "time", "date"}
    if s.lower() in generic_words:
        return False
    return bool(s2)

def _shorten(s: str, lang: str) -> str:
    s = re.split(r"\s[:-]\s", s)[0].strip()
    s = re.sub(r"^(速報|最新|独自)\s*", "", s)
    s = re.sub(r"\s*(とは|について)$", "", s) if lang == "ja" else s
    return s.strip()

def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

# ──────────────────────────────────────────────
# Google News RSS
# ──────────────────────────────────────────────
def _fetch_google_news_titles(lang: str, limit: int = 50) -> list[str]:
    p = NEWS_PARAMS.get(lang) or NEWS_PARAMS["en"]
    url = "https://news.google.com/rss?" + urlencode(p)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=8) as r:
        xml = r.read()
    root = ET.fromstring(xml)
    titles = []
    for item in root.findall(".//item/title"):
        t = (item.text or "").strip()
        if t: titles.append(t)
        if len(titles) >= limit: break
    return titles

# ──────────────────────────────────────────────
# Wikipedia Pageviews
# ──────────────────────────────────────────────
def _fetch_wikipedia_hot(lang: str, limit: int = 50) -> list[str]:
    proj = WIKI_PROJECT.get(lang, "en.wikipedia")
    y = (dt.datetime.utcnow() - dt.timedelta(days=1))
    url = (
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
        f"{proj}/all-access/{y:%Y/%m/%d}"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    pages = data.get("items", [{}])[0].get("articles", []) if data else []
    out = []
    for p in pages:
        title = p.get("article") or ""
        if not title or title.startswith(("Special:", "Main_Page")):
            continue
        title = title.replace("_", " ")
        out.append(title)
        if len(out) >= limit: break
    return out

# ──────────────────────────────────────────────
# スコアリング＆正規化
# ──────────────────────────────────────────────
def _normalize_and_score(candidates: list[str], lang: str, source_bias: float) -> list[tuple[str, float]]:
    scored = []
    for rank, raw in enumerate(candidates):
        t = _clean_title(raw)
        t = _shorten(t, lang)
        if not _is_good_len(t, lang):
            continue
        if not _looks_term_like(t, lang):
            continue
        score = source_bias * (1.0 + 1.0 / (1 + rank))
        if lang in ("en", "fr", "es", "pt", "id"):
            words = re.findall(rf"[{_LAT}]+", t)
            if words and all(w[0].isupper() for w in words[:2]):
                score += 0.2
            if len(words) <= 3:
                score += 0.2
        else:
            ln = len(t)
            if 2 <= ln <= 16:
                score += 0.3
        scored.append((t, score))
    return scored

def _merge_rankings(gn_scores, wp_scores, topk=60):
    agg = {}
    for t, s in gn_scores + wp_scores:
        agg[t] = agg.get(t, 0.0) + s
    jittered = [(t, sc + random.uniform(0, 0.05)) for t, sc in agg.items()]
    jittered.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in jittered[:topk]]

# ──────────────────────────────────────────────
# キャッシュ
# ──────────────────────────────────────────────
def _load_cache(path: Path, ttl_min: int) -> list[str] | None:
    if not path.exists(): return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(obj.get("_ts", 0)) <= ttl_min * 60:
            return obj.get("items") or None
    except Exception:
        return None
    return None

def _save_cache(path: Path, items: list[str]):
    try:
        path.write_text(json.dumps({"_ts": time.time(), "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ──────────────────────────────────────────────
# 公開API
# ──────────────────────────────────────────────
def get_trend_candidates(
    audio_lang: str,
    cache_dir: Path,
    limit: int = 30,
    cache_ttl_minutes: int = 60,
) -> list[str]:
    """
    指定言語のトレンド候補を返す。
    取得できない場合は例外をraise（フォールバックなし）
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"trends_{audio_lang}.json"

    cached = _load_cache(cache_path, cache_ttl_minutes)
    if cached:
        return cached[:limit]

    try:
        news = _fetch_google_news_titles(audio_lang, limit=60)
    except Exception as e:
        print(f"[WARN] Google News fetch failed: {e}")
        news = []
    try:
        wiki = _fetch_wikipedia_hot(audio_lang, limit=60)
    except Exception as e:
        print(f"[WARN] Wikipedia fetch failed: {e}")
        wiki = []

    if not news and not wiki:
        raise RuntimeError(f"No trend data fetched for {audio_lang}")

    gn_scores = _normalize_and_score(news, audio_lang, source_bias=1.0)
    wp_scores = _normalize_and_score(wiki, audio_lang, source_bias=0.6)
    merged = _merge_rankings(gn_scores, wp_scores, topk=80)
    merged = _dedup(merged)
    if not merged:
        raise RuntimeError(f"No valid trend items after filtering for {audio_lang}")

    out = merged[:limit]
    _save_cache(cache_path, out)
    return out


# --- ここから末尾に追記 ---------------------------------
__all__ = ["get_trend_candidates", "fetch_trending_topics"]

def fetch_trending_topics(audio_lang: str, limit: int = 1, cache_ttl_minutes: int = 60):
    """
    main.py が期待しているラッパー。
    - 既定では 1 件の“テーマ語”を返す（文字列）
    - limit>1 を渡すと候補リストを返す（list[str]）
    """
    from pathlib import Path
    try:
        from config import TEMP  # 既存 temp ディレクトリ
        cache_dir = TEMP
    except Exception:
        cache_dir = Path("temp")

    items = get_trend_candidates(
        audio_lang=audio_lang,
        cache_dir=cache_dir,
        limit=max(1, limit),
        cache_ttl_minutes=cache_ttl_minutes,
    )
    return items[0] if limit == 1 else items
# --- 追記ここまで ---------------------------------------