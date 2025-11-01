# trend_fetcher.py
"""
学習言語ごとのトレンド候補を取得して、学習向きの短い“テーマ語”に正規化して返す（診断ログ付き）。
- ソース: Google News RSS（国・言語別）/ Wikipedia Pageviews（前日トップ）
- フォールバック: 失敗時は例外を raise（呼び出し側で AUTO へ切替可能）
- 依存: 標準ライブラリのみ（APIキー不要）
- キャッシュ: 60分（デフォ）。環境変数で調整可。
- 豊富なデバッグログ: temp/trends/_debug_*.log に保存（TREND_DEBUG=1で詳細）
- 単体実行: python trend_fetcher.py ja などで動作確認
"""

from __future__ import annotations
import json
import os
import re
import time
import random
import datetime as dt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET
from typing import List, Tuple, Optional

# ==========================
# 設定（環境変数で上書き可）
# ==========================
TREND_DEBUG: bool = os.getenv("TREND_DEBUG", "0") == "1"
CACHE_TTL_MIN: int = int(os.getenv("TREND_CACHE_TTL_MIN", "60"))
CANDIDATE_LIMIT: int = int(os.getenv("TREND_CANDIDATE_LIMIT", "30"))
DEFAULT_CACHE_DIR = Path(os.getenv("TREND_CACHE_DIR", "temp/trends"))
HTTP_TIMEOUT_SEC: int = int(os.getenv("TREND_HTTP_TIMEOUT", "10"))
RETRY_TIMES: int = int(os.getenv("TREND_RETRY", "2"))  # 失敗時の再試行回数

# 取得ソースの優先度（mixed/news/wiki）
PREFER_SOURCE: str = os.getenv("TREND_PREFER", "mixed").lower()

# 言語→国別 Google News パラメータ
NEWS_PARAMS = {
    "ja": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
    "en": {"hl": "en", "gl": "US", "ceid": "US:en"},
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
    "fr": {"hl": "fr", "gl": "FR", "ceid": "FR:fr"},
    "es": {"hl": "es", "gl": "ES", "ceid": "ES:es"},
    "pt": {"hl": "pt", "gl": "BR", "ceid": "BR:pt"},
    "id": {"hl": "id", "gl": "ID", "ceid": "ID:id"},
}

# Wikipedia Pageviews のプロジェクト名
WIKI_PROJECT = {
    "ja": "ja.wikipedia",
    "en": "en.wikipedia",
    "ko": "ko.wikipedia",
    "fr": "fr.wikipedia",
    "es": "es.wikipedia",
    "pt": "pt.wikipedia",
    "id": "id.wikipedia",
}

# 正規化ユーティリティ
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


# ==========================
# ログ
# ==========================
def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def _logfile(cache_dir: Path) -> Path:
    _ensure_dir(cache_dir)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return cache_dir / f"_debug_{ts}.log"


def _log(cache_dir: Path, msg: str):
    # 標準出力にも出す
    print(msg)
    try:
        fp = _logfile(cache_dir)
        with fp.open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass  # ログ失敗は無視


def _log_block(cache_dir: Path, title: str, body: str):
    sep = "=" * 10
    _log(cache_dir, f"{sep} {title} {sep}\n{body}\n")


# ==========================
# HTTP
# ==========================
_UA = "Mozilla/5.0 (compatible; TrendFetcher/1.0; +https://example.local)"

def _http_get(url: str, timeout: int, cache_dir: Path, label: str) -> bytes:
    last_err = None
    for attempt in range(1, RETRY_TIMES + 2):
        try:
            req = Request(url, headers={"User-Agent": _UA})
            with urlopen(req, timeout=timeout) as r:
                data = r.read()
            if TREND_DEBUG:
                _log(cache_dir, f"[HTTP] {label} OK (attempt={attempt}, len={len(data)}) url={url}")
            return data
        except (HTTPError, URLError, TimeoutError, Exception) as e:
            last_err = e
            _log(cache_dir, f"[HTTP] {label} FAIL (attempt={attempt}) {e} url={url}")
            time.sleep(min(2 * attempt, 6))
    raise RuntimeError(f"HTTP get failed for {label}: {last_err}")


# ==========================
# 文字列正規化
# ==========================
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
    if not s:
        return False
    if not re.search(rf"[{_CJK}{_LAT}]", s):
        return False
    # 日本語のメディア語尾は除外
    if lang == "ja" and any(s.endswith(x) for x in ("ニュース", "通信", "日報", "タイムズ")):
        return False
    # 完全にストップワードだけの英単語列は除外
    lowers = set(re.findall(r"[a-z]+", s.lower()))
    if lowers and lowers.issubset(STOPWORDS.get(lang, set())):
        return False
    s2 = re.split(r"\s[:-]\s", s)[0].strip()
    return bool(s2)


def _shorten(s: str, lang: str) -> str:
    s = re.split(r"\s[:-]\s", s)[0].strip()
    if lang == "ja":
        s = re.sub(r"^(速報|最新|独自)\s*", "", s)
        s = re.sub(r"\s*(とは|について)$", "", s)
    return s.strip()


def _dedup(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


# ==========================
# フィード取得
# ==========================
def _fetch_google_news_titles(audio_lang: str, cache_dir: Path, limit: int = 60) -> List[str]:
    p = NEWS_PARAMS.get(audio_lang) or NEWS_PARAMS["en"]
    url = "https://news.google.com/rss?" + urlencode(p)
    xml = _http_get(url, HTTP_TIMEOUT_SEC, cache_dir, label="GoogleNewsRSS")
    try:
        root = ET.fromstring(xml)
    except Exception as e:
        _log(cache_dir, f"[XML] parse error GoogleNews: {e}")
        return []

    titles: List[str] = []
    for item in root.findall(".//item/title"):
        t = (item.text or "").strip()
        if t:
            titles.append(t)
        if len(titles) >= limit:
            break

    if TREND_DEBUG:
        sample = "\n".join(titles[:5])
        _log_block(cache_dir, "GoogleNews SAMPLE", sample or "(empty)")
    return titles


def _fetch_wikipedia_hot(audio_lang: str, cache_dir: Path, limit: int = 60) -> List[str]:
    proj = WIKI_PROJECT.get(audio_lang, "en.wikipedia")
    y = (dt.datetime.utcnow() - dt.timedelta(days=1))
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{proj}/all-access/{y:%Y/%m/%d}"
    data = _http_get(url, HTTP_TIMEOUT_SEC, cache_dir, label="WikipediaHot")
    try:
        payload = json.loads(data.decode("utf-8", "ignore"))
    except Exception as e:
        _log(cache_dir, f"[JSON] parse error Wikipedia: {e}")
        return []

    pages = payload.get("items", [{}])[0].get("articles", []) if payload else []
    out: List[str] = []
    for p in pages:
        title = p.get("article") or ""
        if not title or title.startswith(("Special:", "Main_Page")):
            continue
        title = title.replace("_", " ")
        out.append(title)
        if len(out) >= limit:
            break

    if TREND_DEBUG:
        sample = "\n".join(out[:5])
        _log_block(cache_dir, "Wikipedia SAMPLE", sample or "(empty)")
    return out


# ==========================
# スコアリング＆マージ
# ==========================
def _normalize_and_score(candidates: List[str], lang: str, source_bias: float) -> List[Tuple[str, float]]:
    scored: List[Tuple[str, float]] = []
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


def _merge_rankings(gn_scores: List[Tuple[str, float]], wp_scores: List[Tuple[str, float]], topk: int = 80) -> List[str]:
    agg = {}
    for t, s in gn_scores + wp_scores:
        agg[t] = agg.get(t, 0.0) + s
    jittered = [(t, sc + random.uniform(0, 0.05)) for t, sc in agg.items()]
    jittered.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in jittered[:topk]]


# ==========================
# キャッシュ
# ==========================
def _cache_path(cache_dir: Path, audio_lang: str) -> Path:
    return cache_dir / f"trends_{audio_lang}.json"


def _load_cache(cache_dir: Path, audio_lang: str, ttl_min: int) -> Optional[List[str]]:
    path = _cache_path(cache_dir, audio_lang)
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(obj.get("_ts", 0)) <= ttl_min * 60:
            return obj.get("items") or None
    except Exception:
        return None
    return None


def _save_cache(cache_dir: Path, audio_lang: str, items: List[str]):
    path = _cache_path(cache_dir, audio_lang)
    try:
        _ensure_dir(cache_dir)
        path.write_text(
            json.dumps({"_ts": time.time(), "items": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ==========================
# 公開API
# ==========================
def get_trend_candidates(
    audio_lang: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    limit: int = CANDIDATE_LIMIT,
    cache_ttl_minutes: int = CACHE_TTL_MIN,
) -> List[str]:
    """
    指定言語の“候補一覧”を返す（最大 limit 件）。
    取得できない場合は例外を raise（フォールバックは呼び出し側で）。
    """
    _ensure_dir(cache_dir)
    # キャッシュ
    cached = _load_cache(cache_dir, audio_lang, cache_ttl_minutes)
    if cached:
        if TREND_DEBUG:
            _log(cache_dir, f"[CACHE] hit ({audio_lang}) items={len(cached)} ttl={cache_ttl_minutes}min")
        return cached[:limit]

    # フェッチ
    news, wiki = [], []
    try:
        news = _fetch_google_news_titles(audio_lang, cache_dir, limit=60)
    except Exception as e:
        _log(cache_dir, f"[WARN] Google News fetch failed: {e}")
    try:
        wiki = _fetch_wikipedia_hot(audio_lang, cache_dir, limit=60)
    except Exception as e:
        _log(cache_dir, f"[WARN] Wikipedia fetch failed: {e}")

    if not news and not wiki:
        raise RuntimeError(f"No trend data fetched for {audio_lang}")

    # 正規化＆スコア
    gn_scores = _normalize_and_score(news, audio_lang, source_bias=1.0)
    wp_scores = _normalize_and_score(wiki, audio_lang, source_bias=0.6)

    if PREFER_SOURCE == "news":
        merged = [t for t, _ in sorted(gn_scores, key=lambda x: x[1], reverse=True)]
    elif PREFER_SOURCE == "wiki":
        merged = [t for t, _ in sorted(wp_scores, key=lambda x: x[1], reverse=True)]
    else:
        merged = _merge_rankings(gn_scores, wp_scores, topk=80)

    merged = _dedup(merged)
    if TREND_DEBUG:
        _log_block(cache_dir, "SCORED TOP10", "\n".join(merged[:10]) or "(empty)")

    if not merged:
        raise RuntimeError(f"No valid trend items after filtering for {audio_lang}")

    out = merged[:limit]
    _save_cache(cache_dir, audio_lang, out)
    return out


def fetch_trending_topics(
    audio_lang: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    limit: int = CANDIDATE_LIMIT,
    cache_ttl_minutes: int = CACHE_TTL_MIN,
) -> str:
    """
    メインの公開関数：1件だけ“テーマ語”を返す。
    - 成功: 候補リストからランダムではなく上位を軽くシャッフルして先頭を返す（偏り防止）
    - 失敗: 例外を raise（main.py 側で AUTO へフォールバックする想定）
    """
    cands = get_trend_candidates(
        audio_lang=audio_lang,
        cache_dir=cache_dir,
        limit=limit,
        cache_ttl_minutes=cache_ttl_minutes,
    )
    # 上位3～5件を軽くシャッフルし先頭を返す（完全固定回避）
    top = cands[: max(3, min(5, len(cands)))]
    random.shuffle(top)
    picked = top[0] if top else cands[0]
    if TREND_DEBUG:
        _log(cache_dir, f"[PICK] {audio_lang} -> '{picked}' (from {len(cands)} candidates)")
    return picked


# ==========================
# 単体テスト用CLI
# ==========================
if __name__ == "__main__":
    import sys
    lang = sys.argv[1] if len(sys.argv) >= 2 else "ja"
    try:
        print(f"=== Trend test for lang={lang} ===")
        topic = fetch_trending_topics(lang)
        print("PICKED:", topic)
        print(f"Log dir: {DEFAULT_CACHE_DIR.resolve()}")
    except Exception as e:
        print("[ERROR]", e)
        print(f"Log dir: {DEFAULT_CACHE_DIR.resolve()}")
        sys.exit(1)