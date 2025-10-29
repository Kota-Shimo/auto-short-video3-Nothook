# ================= upload_youtube.py =================
"""
YouTube へ動画をアップロードするユーティリティ。
複数アカウント対応（トークンを account ラベルで切替）。
"""

from pathlib import Path
from typing import List, Optional
import pickle, re, logging, time, sys
from dataclasses import dataclass

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http      import MediaFileUpload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

# ── OAuth / API 設定 ─────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_TOKEN_DIR = Path("tokens")          # トークン保存フォルダ
DEFAULT_TOKEN_DIR.mkdir(exist_ok=True)
# ────────────────────────────────────────────────────

# ------------------------------------------------------
# ✅ カスタムサムネイルをセットするヘルパー
def _set_thumbnail(service, video_id: str, thumb_path: Path):
    """アップロード済み video_id に thumb_path を適用"""
    service.thumbnails().set(
        videoId=video_id,
        media_body=str(thumb_path)
    ).execute()
# ------------------------------------------------------

def _get_service(account_label: str = "default"):
    """
    account_label : 任意の識別子。複数アカウントで token_<label>.pkl を使い分ける。
    """
    token_path = DEFAULT_TOKEN_DIR / f"token_{account_label}.pkl"

    if token_path.exists():
        creds = pickle.loads(token_path.read_bytes())
        # 有効期限切れなら自動リフレッシュ
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # リフレッシュ後を保存
            token_path.write_bytes(pickle.dumps(creds))
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
        token_path.write_bytes(pickle.dumps(creds))

    # ✅ 複数アカウント同時処理時のディスカバリキャッシュ競合を防止
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ── タイトル安全化（念のための最終チェック）────────────────
def _sanitize_title(raw: str) -> str:
    """空・改行入りを防ぎ、100字以内に丸める"""
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    if len(title) > 100:
        title = title[:97] + "..."
    return title or "Auto Short #Shorts"
# ────────────────────────────────────────────────────


@dataclass
class _RetryPolicy:
    max_attempts: int = 5
    base_sleep: float = 2.0  # 秒（指数バックオフ）


def _is_quota_or_limit(e: HttpError) -> bool:
    s = str(e).lower()
    return ("quota" in s) or ("uploadlimitexceeded" in s) or ("rateLimitExceeded".lower() in s)


def _resumable_insert(service, body, media: MediaFileUpload, retry=_RetryPolicy()):
    """
    公式推奨のレジューム・アップロードループ。
    500系/一時的エラーは指数バックオフで再試行。
    """
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    attempt = 0
    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
            # 進捗表示（任意）
            if status:
                pct = int(status.progress() * 100)
                print(f"⬆️  Uploading... {pct}%")
        except HttpError as e:
            attempt += 1
            # 明確な不可（クォータ/アップロード上限）は即時伝達
            if _is_quota_or_limit(e):
                raise RuntimeError(
                    f"[YouTube] クォータ/上限エラーのためアップロード中断: {e}"
                ) from e

            # 5xx や一時的エラーはリトライ
            if attempt < retry.max_attempts and (e.resp.status >= 500 or "backendError" in str(e)):
                sleep = retry.base_sleep * (2 ** (attempt - 1))
                print(f"⚠️  一時的エラー({e.resp.status})。{sleep:.1f}s 後に再試行 {attempt}/{retry.max_attempts} ...")
                time.sleep(sleep)
                continue
            # それ以外はそのまま上げる
            raise
        except Exception as e:
            attempt += 1
            if attempt < retry.max_attempts:
                sleep = retry.base_sleep * (2 ** (attempt - 1))
                print(f"⚠️  ネットワーク等の例外。{sleep:.1f}s 後に再試行 {attempt}/{retry.max_attempts} ... ({e})")
                time.sleep(sleep)
                continue
            raise

    return response


def upload(
    video_path: Path,
    title: str,
    desc: str,
    tags: Optional[List[str]] = None,
    privacy: str = "public",
    account: str = "default",
    thumbnail: Path | None = None,  # カスタムサムネ
    default_lang: str = "en",       # ★ 動画言語
):
    """
    video_path : Path to .mp4
    title      : YouTube title
    desc       : Description（0–5000 文字）
    tags       : ["tag1", ...]   (optional, 最大 500 個)
    privacy    : "public" / "unlisted" / "private"
    account    : token ラベル（複数アカウント切替用）
    thumbnail  : Path to .jpg / .png（カスタムサムネ）※任意
    default_lang: ISO 639-1 言語コード (例: "en", "ja")
    """
    service = _get_service(account)

    # ---- 最終ガード ----
    title = _sanitize_title(title)
    if len(desc) > 5000:
        desc = desc[:4997] + "..."

    body = {
        "snippet": {
            "title":       title,
            "description": desc,
            "tags":        tags or [],
            "categoryId":  "27",  # Education
            "defaultLanguage": default_lang,           # UI言語
            "defaultAudioLanguage": default_lang,      # 音声言語
        },
        "status": {
            "privacyStatus": privacy,
            "license": "youtube",       # 標準ライセンス
            "selfDeclaredMadeForKids": False,  # 年齢制限なし
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)

    try:
        resp = _resumable_insert(service, body, media)
    except RuntimeError as e:
        # クォータ/上限を明確にログ
        logging.error(str(e))
        raise
    except HttpError as e:
        # 典型 403/401 の補助メッセージ
        msg = str(e)
        if "invalidCredentials" in msg or "unauthorized" in msg or "401" in msg:
            raise RuntimeError(
                f"[YouTube] 認証エラー（トークン期限切れ/権限）: account={account}. もう一度認可してください。詳細: {e}"
            ) from e
        raise

    video_id = resp["id"]
    url = f"https://youtu.be/{video_id}"
    print("✅ YouTube Upload Done →", url)

    # ---- カスタムサムネイル (待ち時間 + try/except) ----
    if thumbnail and thumbnail.exists():
        time.sleep(10)  # 動画登録直後は反映不安定なので待つ
        try:
            _set_thumbnail(service, video_id, thumbnail)
            print("🖼  Custom thumbnail set.")
        except HttpError as e:
            print(f"⚠️  Thumbnail set failed: {e}")

    logging.info("YouTube URL: %s (account=%s)", url, account)
    return url
# ====================================================