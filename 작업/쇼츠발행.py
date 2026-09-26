# -*- coding: utf-8 -*-
"""깃허브 액션이 돌리는 인스타 릴스 + 스레드 + 페북 페이지 릴스 발행 스크립트. 사용자가 직접 만질 일 없음.
이 저장소에는 영상이 없다(영상은 Cloudflare R2). 여기서는 예약표(쇼츠예약.json)만 본다.

하는 일:
  0) 금고(토큰.enc)를 Secrets 의 IG_ACCESS_TOKEN 으로 열어 60일 인스타 토큰·스레드 토큰을 꺼낸다. 토큰 검사.
     인스타 토큰이 죽었으면 아무것도 건드리지 않고 오류기록.txt 한 줄 + 종료코드 1 (액션 실패 → 이메일).
     스레드 토큰이 없거나 죽었으면 인스타만 하고 스레드는 건너뛴다(기록 남김).
     페북은 같은 60일 사용자 토큰에 pages_manage_posts·publish_video 권한이 있을 때만(없으면 건너뜀, 기록 남김). 페이지 토큰은 매번 GET /{PAGE_ID}?fields=access_token 으로 뽑는다.
  0-b) 유튜브(2026-09-19): 금고에 youtube_refresh_token 이 있으면 refresh → 액세스 토큰 → channels.list(mine) 로 명운보감인지 확인.
     없거나 죽었으면 유튜브만 건너뛴다(기록 남김).
  1-a) 유튜브: youtube_status 가 "대기"인 건은 publish_at 이 지나면 R2 에서 mp4 를 받아 유튜브에 올리고 바로 공개한다(2026-09-22~).
     (전엔 미리 올려 예약 공개했는데 사장님 지시로 바꿈. 코드상 publish_at 이 15분 이상 앞이면 여전히 예약 공개가 되지만 이제 그 경우는 안 온다.) → youtube_status "공개", youtube_url.
     하루 한도(API 10,000 = 업로드 6편)·인증 오류면 대기 유지, 영상 규격 오류면 "실패", 그 외 3회.
  1) 쇼츠예약.json 에서 publish_at 이 지난 건마다
     - 인스타: status 가 "대기"면 POST /{IG_USER_ID}/media (REELS) → 컨테이너 FINISHED 까지 → media_publish → status "게시"
     - 스레드: threads_status 가 "대기"면 POST /{THREADS_USER_ID}/threads (TEXT, 글만) → FINISHED → threads_publish → threads_status "게시"
       → 첫 답글(reply_to_id)에 만세력 문장 + 사이트 링크 (본문엔 링크 없음). 답글 실패는 기록만.
     - 페북: fb_status 가 "대기"면 POST /{PAGE_ID}/video_reels (start) → rupload 에 file_url(R2 주소) → 업로드 완료까지 → (finish, PUBLISHED, description=fb_caption) → fb_status "게시"
       캡션(fb_caption)은 PC 가 만든 세 번째 벌(존댓말·긴 설명·링크 본문). fb_caption 없는 옛 건은 페북에 안 올린다.
     - 컨테이너·video id 는 만들자마자 예약표에 적어 다음 회차에 이어서 본다.
  2) 오류는 종류별로 (인스타·스레드·페북 각각):
     - 인증(190, 102, 10, 200~299): 대기 유지. 인스타면 액션 실패, 스레드·페북이면 기록만
     - 속도 제한(4, 17, 32, 613, 하루 한도 소진): 대기 유지, 다음 회차
     - 영상 규격(2207xxx, unsupported/aspect ratio/too short/too long, 컨테이너 ERROR): 즉시 "실패" (다시 해도 안 됨)
     - 그 외(전송 실패, 시간 초과 등): attempts +1, 3회까지 대기 유지, 넘으면 "실패". last_error 에 마지막 이유.
예약표 한 건: id, video_url, caption, publish_at, status(인스타), youtube_url + 액션이 쓰는 ig_container_id,
             youtube_status, yt_title, yt_description, yt_tags(PC 가 실음), youtube_video_id, youtube_uploaded_at, youtube_attempts, youtube_error(액션이 씀), ig_media_id, posted_at, attempts, last_error,
             threads_text(스레드글.py 가 만든 글), threads_status, threads_container_id, threads_media_id, threads_posted_at, threads_attempts, threads_entities(가림 위치), threads_error, threads_reply_id,
             fb_caption, fb_status, fb_video_id, fb_post_id, fb_posted_at, fb_attempts, fb_error
영상 삭제는 PC 쪽 upload_instagram.py --cleanup 이 R2에서 한다(인스타 게시 20시간 뒤. 스레드·페북이 아직 대기면 48시간까지).
로컬 시험: python 작업/쇼츠발행.py --dry-run  (토큰 없어도 됨. 아무것도 안 바꿈)
2026-09-25: 예약표·발행기록·오류기록은 깃허브 파일이 아니라 **R2 창고(shorts/, 쇼츠창고.py)** 다. 커밋 없음. PC 와 같은 것을 본다.
"""
import os
import re
import sys
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import 쇼츠창고                    # 예약표·기록은 전부 R2 창고 shorts/ (2026-09-25 사장님 지시). 깃허브엔 안 남긴다
LOG_OK = "발행기록.txt"
LOG_ERR = "오류기록.txt"
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
VAULT_KEY = os.environ.get("IG_ACCESS_TOKEN", "").strip()   # 금고 열쇠(만료 없는 페이지 토큰). 게시에는 안 쓴다
IG_TOKEN = ""                                                 # 게시용 60일 인스타 토큰. 금고에서 꺼낸다
TH_TOKEN, TH_USER_ID, TH_USERNAME = "", "", ""                # 스레드. 금고에 있으면 쓴다
FB_TOKEN, FB_PAGE_NAME = "", ""                               # 페북 페이지 토큰(사용자 토큰으로 매번 뽑음). 권한 있을 때만
YT_TOKEN, YT_CHANNEL_TITLE = "", ""                           # 유튜브 액세스 토큰(금고의 refresh_token 으로 매번 뽑음). 금고에 있을 때만
YT_CREDS = {}                                                 # 금고의 youtube_client_id·client_secret·refresh_token. 값은 안 찍는다
YT_CHANNEL_ID = "UCSs1eCimg-mvZPVIZtzNAKA"                   # 명운보감. 다른 채널이면 게시 전에 멈춘다. = PC youtube_token.py
YT_API = "https://www.googleapis.com/youtube/v3/"
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
IG_SCOPES = set()                                             # 사용자 토큰 권한(debug_token). 페북 권한 확인용
IG_USERNAME = "luck.arcade"           # 운빨연구소. 다른 계정이면 게시 전에 멈춘다
PAGE_ID = "1339892089198082"          # 페이스북 페이지 hulit (릴스 올리는 곳). = 토큰갱신.py PAGE_ID
FB_SCOPES = {"pages_manage_posts", "publish_video"}   # 페이지 릴스에 필요한 권한. 없으면 PC 에서 python fb_token.py
GRAPH = "https://graph.facebook.com/v26.0/"
RUPLOAD = "https://rupload.facebook.com/video-upload/v26.0/"
THREADS = "https://graph.threads.net/v1.0/"
KST = ZoneInfo("Asia/Seoul")
DRY = "--dry-run" in sys.argv
MAX_ATTEMPTS = 3

# ── 몰아서 안 올리기 (2026-09-22 사장님 지시 "밀린 게 2개 이상일 때 한꺼번에 올라가면 SNS 가 싫어한다") ──
# 깨우기(PC·워커 10분마다)가 있어 밀릴 일이 거의 없지만, 둘 다 죽었다 살아났을 때의 안전장치.
MIN_GAP_MIN = {"ig": 180, "fb": 180, "yt": 180, "th": 45}   # 같은 SNS 에 마지막 게시 후 이만큼(분) 안 지났으면 다음 회차로.
                                                             # 스레드는 하루 3~5개를 1시간 간격으로 올리는 계획이라 짧게.
MAX_LATE_H = 24            # 이만큼 넘게 밀린 건 안 올리고 '보류'로 두고 사장님께 묻는다 (새벽 3시에 어제 것이 올라가는 사고 방지)
POSTED_KEY = {"ig": "posted_at", "th": "threads_posted_at", "fb": "fb_posted_at", "yt": "youtube_uploaded_at"}
STATUS_KEY = {"ig": "status", "th": "threads_status", "fb": "fb_status", "yt": "youtube_status"}
NAME = {"ig": "인스타", "th": "스레드", "fb": "페북", "yt": "유튜브"}


def tg_send(text):
    """텔레그램 알림 (Secrets TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID). 없으면 조용히 건너뜀."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat or DRY:
        return
    try:
        body = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode("utf-8")
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, body, timeout=30).read()
    except Exception as e:
        print("텔레그램 실패: %s" % e)


def spread(q, t, due, tgt, save):
    """한 회차에 SNS 마다 1개만, 마지막 게시 후 MIN_GAP_MIN 지나야, 하루 넘게 밀린 건 보류. 올릴 목록을 돌려준다."""
    if not due:
        return due
    name, st_key, posted_key = NAME[tgt], STATUS_KEY[tgt], POSTED_KEY[tgt]
    due = sorted(due, key=lambda it: it["publish_at"])
    fresh = []
    for it in due:
        if t - parse(it["publish_at"]) > timedelta(hours=MAX_LATE_H):
            it[st_key] = "보류"
            log(LOG_ERR, "%s %s %s 보류: 예약(%s)이 하루 넘게 지남. 올리려면 %s 를 '대기'로" % (stamp(), it["id"], name, it["publish_at"], st_key))
            tg_send("⏸ %s 보류 — 예약 %s 이 하루 넘게 밀렸어.\n%s\n\n올릴 거면 말해줘 (지금은 안 올림)" % (name, it["publish_at"], it["id"]))
            save()
        else:
            fresh.append(it)
    last = [parse(it[posted_key]) for it in q if it.get(posted_key)]
    if last and (t - max(last)) < timedelta(minutes=MIN_GAP_MIN[tgt]):
        if fresh:
            print("  %s: 마지막 게시 %s 로부터 %d분 안 지나 이번 회차는 쉼 (%d건 대기)" % (name, max(last).strftime("%H:%M"), MIN_GAP_MIN[tgt], len(fresh)))
        return []
    if len(fresh) > 1:
        print("  %s: %d건 밀림 → 이번 회차엔 1개만, 나머지는 %d분 뒤부터" % (name, len(fresh), MIN_GAP_MIN[tgt]))
    return fresh[:1]

# ── 예약표 점검: 하루에 영상이 MAX_VIDEOS_PER_DAY 넘게 잡혀 있으면 알린다 (2026-09-22 사고: 낮에 3편). 막지는 않는다(PC schedule.py 가 막는다) ──
MAX_VIDEOS_PER_DAY = 2                     # = PC schedule.py SLOTS 개수(낮·밤)
PILEUP_LOG = "몰림경고.json"                # {날짜: 개수} 같은 날·같은 개수는 한 번만 알린다 (창고)


def warn_pileup(q, t):
    per = {}
    for it in q:
        if not it.get("video_url"):
            continue                                                   # 스레드 글만 있는 건은 영상이 아니다
        live = (it.get("status", "대기") in ("대기", "게시") or it.get("youtube_status") in ("대기", "예약", "공개")
                or it.get("fb_status") in ("대기", "게시"))
        if live and it.get("publish_at", "")[:10] >= t.strftime("%Y-%m-%d"):
            per.setdefault(it["publish_at"][:10], []).append(it["id"])
    bad = {d: ids for d, ids in per.items() if len(ids) > MAX_VIDEOS_PER_DAY}
    if not bad:
        return
    try:
        seen = 쇼츠창고.열기().읽기(PILEUP_LOG) or {}
    except Exception:
        seen = {}
    for d, ids in sorted(bad.items()):
        if seen.get(d) == len(ids):
            continue
        line = "%s 예약표 점검: %s 에 영상 %d편 (하루 최대 %d): %s" % (stamp(), d, len(ids), MAX_VIDEOS_PER_DAY, ", ".join(ids))
        log(LOG_ERR, line)
        tg_send("⚠ " + line + "\n\nPC 에서 python schedule.py list 로 보고 python schedule.py move 로 옮겨")
        seen[d] = len(ids)
    if not DRY:
        쇼츠창고.열기().쓰기(PILEUP_LOG, seen)


POLL_SEC, POLL_MAX = 10, 30          # 10초 × 30 = 5분
THREADS_TEXT_MAX = 500
THREADS_REPLY = "사람이 봐주는 데 아님. 사주 달력표 그대로 뽑아주는 곳. 네 년생 30초, 링크 ↓" + "\n" + "https://sajuarcade.com"   # = PC config.THREADS_REPLY
REPLY_EVERY_DAYS = 5                                  # 링크 답글은 5일에 1회 (2026-09-19 사장님 지시 "웹사이트 댓글 5일에 1회"). 나머지 글은 본문만
REPLY_LOG = "스레드링크기록.json"                      # {"last": "YYYY-MM-DD HH:MM"} 마지막으로 링크 답글 단 시각 (창고)

AUTH_CODES = {190, 102, 10} | set(range(200, 300))
RATE_CODES = {4, 17, 32, 613}
SPEC_WORDS = ("unsupported", "aspect ratio", "too short", "too long", "invalid video", "media download failed", "not supported")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def now():
    return datetime.now(KST).replace(tzinfo=None)


def stamp():
    return now().strftime("%Y-%m-%d %H:%M")


def parse(t):
    return datetime.strptime(t, "%Y-%m-%d %H:%M")


def log(path, line):
    print(line)
    if not DRY:
        쇼츠창고.열기().붙이기(path, line)


class GraphError(Exception):
    """그래프 API 오류. kind = auth | rate | spec | other"""
    def __init__(self, msg, code=None, subcode=None, http=None):
        super().__init__(msg)
        self.code, self.subcode, self.http = code, subcode, http

    @property
    def kind(self):
        m = str(self).lower()
        if self.code in AUTH_CODES:
            return "auth"
        if self.code in RATE_CODES:
            return "rate"
        if (self.subcode and 2207000 <= self.subcode < 2208000) or any(w in m for w in SPEC_WORDS):
            return "spec"
        return "other"

    def __str__(self):
        base = super().__str__()
        tag = " ".join(x for x in ("code %s" % self.code if self.code is not None else "",
                                   "sub %s" % self.subcode if self.subcode else "",
                                   "HTTP %s" % self.http if self.http else "") if x)
        return ("[%s] " % tag if tag else "") + base


def _call(base, token, method, path, **params):
    params["access_token"] = token
    data = urllib.parse.urlencode(params).encode("utf-8")
    url = base + path
    if method == "GET":
        url += "?" + data.decode("utf-8"); data = None
    req = urllib.request.Request(url, data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body).get("error", {})
        except Exception:
            err = {}
        raise GraphError(err.get("message") or body[:300], code=err.get("code"),
                         subcode=err.get("error_subcode"), http=e.code)
    except Exception as e:
        raise GraphError("전송 실패: %s" % e)


def graph(method, path, **params):
    return _call(GRAPH, IG_TOKEN, method, path, **params)


def threads(method, path, **params):
    return _call(THREADS, TH_TOKEN, method, path, **params)


def fb(method, path, **params):
    return _call(GRAPH, FB_TOKEN, method, path, **params)


# ── 0) 금고·토큰 검사 ─────────────────────────────────────────────────
def open_vault():
    """토큰.enc 를 열어 IG_TOKEN(+스레드)을 채운다. 실패면 이유 문자열."""
    global IG_TOKEN, TH_TOKEN, TH_USER_ID, TH_USERNAME
    if not VAULT_KEY:
        return "IG_ACCESS_TOKEN(금고 열쇠) 비어 있음"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import 금고
    except ImportError:
        return "pynacl 없음 (워크플로에 pip install pynacl)"
    if not 금고.VAULT.exists():
        # 금고가 아직 없으면 열쇠(페이지 토큰)로 인스타만 게시한다. 발행이 끊기는 구간이 없게.
        IG_TOKEN = VAULT_KEY
        print("토큰.enc 없음 → 페이지 토큰으로 인스타만 게시 (PC 에서 python ig_token.py 하면 60일 토큰으로 바뀜)")
        return None
    try:
        v = 금고.load(VAULT_KEY)
    except Exception as e:
        return "금고를 못 열음(열쇠 태그 %s): %s" % (금고.key_tag(VAULT_KEY), type(e).__name__)
    IG_TOKEN = v.get("user_token", "")
    YT_CREDS.update({k: v.get("youtube_" + k, "") for k in ("client_id", "client_secret", "refresh_token")})
    TH_TOKEN = v.get("threads_token", "")
    TH_USER_ID = str(v.get("threads_user_id", "") or "")
    TH_USERNAME = v.get("threads_username", "")
    return None if IG_TOKEN else "금고 안에 인스타 토큰 없음"


def check_token():
    """인스타 토큰 검사. 값은 절대 출력하지 않는다. 문제면 이유 문자열, 정상이면 None"""
    if not IG_USER_ID:
        return "IG_USER_ID 비어 있음 (저장소 Settings → Secrets 에 등록)"
    err = open_vault()
    if err:
        return err
    try:
        d = graph("GET", "debug_token", input_token=IG_TOKEN).get("data", {})
    except GraphError as e:
        return "debug_token 실패: %s" % e
    info = {k: d.get(k) for k in ("type", "is_valid", "expires_at", "data_access_expires_at")}
    print("인스타 토큰:", info, "scopes:", d.get("scopes"))
    IG_SCOPES.clear(); IG_SCOPES.update(d.get("scopes") or [])
    if not d.get("is_valid"):
        return "토큰이 유효하지 않음 (is_valid=false). token-refresh 실행 또는 PC 에서 ig_token.py"
    if d.get("expires_at"):
        exp = datetime.fromtimestamp(d["expires_at"], KST).replace(tzinfo=None)
        left = (exp - now()).days
        print("60일 토큰 만료: %s (%d일 남음)" % (exp.strftime("%Y-%m-%d %H:%M"), left))
        if exp <= now():
            return "60일 토큰 만료됨 (%s). token-refresh 가 안 돈 것. PC 에서 ig_token.py" % exp.strftime("%Y-%m-%d %H:%M")
        if left <= 7:
            print("주의: 만료 7일 이내. token-refresh 워크플로가 도는지 확인")
    dae = d.get("data_access_expires_at")
    if dae:
        left = (datetime.fromtimestamp(dae, KST).replace(tzinfo=None) - now()).days
        if left <= 10:
            print("주의: data_access_expires_at 까지 %d일. 게시가 막히면 ig_token.py 로 토큰 재발급" % left)
    need = {"instagram_basic", "instagram_content_publish"}
    missing = need - set(d.get("scopes") or [])
    if missing:
        return "토큰 권한 부족: %s" % ", ".join(sorted(missing))
    try:
        u = graph("GET", IG_USER_ID, fields="username")
    except GraphError as e:
        return "인스타 계정 조회 실패: %s" % e
    if u.get("username") != IG_USERNAME:
        return "IG_USER_ID 가 @%s 가 아님: %s" % (IG_USERNAME, u)
    print("인스타 계정: @%s (%s)" % (u.get("username"), IG_USER_ID))
    return None


def check_threads():
    """스레드 토큰 검사. 쓸 수 있으면 True. 없거나 죽었으면 False (인스타는 계속)"""
    global TH_USERNAME
    if not TH_TOKEN or not TH_USER_ID:
        print("스레드: 금고에 토큰 없음 → 건너뜀 (PC 에서 python threads_token.py)")
        return False
    try:
        me = threads("GET", "me", fields="id,username")
    except GraphError as e:
        log(LOG_ERR, "%s 스레드 토큰 검사 실패 (스레드만 건너뜀): %s" % (stamp(), e))
        return False
    if str(me.get("id")) != TH_USER_ID:
        log(LOG_ERR, "%s 스레드 계정 불일치: 금고 %s, 실제 %s (스레드만 건너뜀)" % (stamp(), TH_USER_ID, me))
        return False
    TH_USERNAME = me.get("username") or TH_USERNAME
    print("스레드 계정: @%s (%s)" % (TH_USERNAME, TH_USER_ID))
    return True


def check_fb():
    """페북 페이지 릴스. 사용자 토큰에 권한 2개가 있으면 페이지 토큰을 뽑아 True. 없거나 실패면 False (인스타·스레드는 계속)"""
    global FB_TOKEN, FB_PAGE_NAME
    missing = FB_SCOPES - IG_SCOPES
    if missing:
        print("페북: 권한 없음(%s) → 건너뜀 (PC 에서 python fb_token.py 로 권한 추가)" % ", ".join(sorted(missing)))
        return False
    try:
        p = graph("GET", PAGE_ID, fields="name,access_token")
    except GraphError as e:
        log(LOG_ERR, "%s 페북 페이지 토큰 실패 (페북만 건너뜀): %s" % (stamp(), e))
        return False
    FB_TOKEN, FB_PAGE_NAME = p.get("access_token", ""), p.get("name", "")
    if not FB_TOKEN:
        log(LOG_ERR, "%s 페북 페이지 토큰 없음 (페북만 건너뜀): %s" % (stamp(), {k: p.get(k) for k in ("id", "name")}))
        return False
    print("페북 페이지: %s (%s)" % (FB_PAGE_NAME, PAGE_ID))
    return True


# ── 유튜브 ──────────────────────────────────────────────────────────
def yt_call(method, url, body=None, headers=None, raw=None, timeout=300):
    """유튜브 API. (JSON 응답, 응답 헤더). 실패면 GraphError(kind 는 유튜브 기준으로 접음)"""
    h = {"Authorization": "Bearer " + YT_TOKEN}
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    if body is not None:
        h["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
            return (json.loads(txt) if txt.strip() else {}), r.headers
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(txt).get("error", {})
            reason = ((err.get("errors") or [{}])[0].get("reason") or "")
            msg = "%s %s" % (reason, err.get("message") or "")
        except Exception:
            reason, msg = "", txt[:300]
        raise GraphError(msg.strip(), code=_yt_code(e.code, reason), http=e.code)
    except Exception as e:
        raise GraphError("전송 실패: %s" % e)


def _yt_code(http, reason):
    """유튜브 오류를 GraphError.kind 로 접기: 401/권한 → 190(auth), 한도 → 4(rate), 그 외 None(other)"""
    r = (reason or "")
    if http == 401 or r in ("authError", "forbidden", "insufficientPermissions", "youtubeSignupRequired"):
        return 190
    if "quota" in r.lower() or "rateLimit" in r or http == 429:
        return 4
    return None


def check_youtube():
    """금고의 refresh_token 으로 액세스 토큰을 받고 채널이 명운보감인지 본다. 되면 True, 아니면 False(유튜브만 건너뜀)"""
    global YT_TOKEN, YT_CHANNEL_TITLE
    if not YT_CREDS.get("refresh_token"):
        print("유튜브: 금고에 토큰 없음 → 건너뜀 (PC 에서 python youtube_token.py)")
        return False
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": YT_CREDS["client_id"],
                                   "client_secret": YT_CREDS["client_secret"], "refresh_token": YT_CREDS["refresh_token"]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data), timeout=60) as r:
            YT_TOKEN = json.load(r).get("access_token", "")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(body); why = "%s %s" % (j.get("error"), j.get("error_description"))
        except Exception:
            why = body[:200]
        log(LOG_ERR, "%s 유튜브 토큰 실패 (유튜브만 건너뜀. PC 에서 python youtube_token.py): %s" % (stamp(), why))
        return False
    except Exception as e:
        log(LOG_ERR, "%s 유튜브 토큰 전송 실패 (유튜브만 건너뜀): %s" % (stamp(), e))
        return False
    if not YT_TOKEN:
        log(LOG_ERR, "%s 유튜브 액세스 토큰 없음 (유튜브만 건너뜀)" % stamp())
        return False
    try:
        j, _ = yt_call("GET", YT_API + "channels?part=id,snippet&mine=true")
    except GraphError as e:
        if "insufficient" in str(e).lower() or "scope" in str(e).lower():
            YT_CHANNEL_TITLE = "명운보감"
            print("유튜브 토큰 정상 (업로드 권한만 있어 채널 조회는 생략. 업로드 응답의 channelId 로 확인)")
            return True
        log(LOG_ERR, "%s 유튜브 채널 조회 실패 (유튜브만 건너뜀): %s" % (stamp(), e))
        return False
    items = j.get("items") or []
    if not items or items[0].get("id") != YT_CHANNEL_ID:
        log(LOG_ERR, "%s 유튜브 채널 불일치 (유튜브만 건너뜀): %s" % (stamp(), [(i.get("id"), i.get("snippet", {}).get("title")) for i in items]))
        return False
    YT_CHANNEL_TITLE = items[0]["snippet"].get("title", "")
    print("유튜브 채널: %s (%s)" % (YT_CHANNEL_TITLE, YT_CHANNEL_ID))
    return True


def yt_state(it):
    """유튜브 상태. youtube_status 가 없는 옛 건(PC 가 직접 올린 것)은 '없음'"""
    return it.get("youtube_status") or "없음"


def yt_download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "shorts-publish"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        raise GraphError("R2 영상 받기 실패 HTTP %s (%s)" % (e.code, url), subcode=2207000 if e.code == 404 else None)
    except Exception as e:
        raise GraphError("R2 영상 받기 실패: %s" % e)
    size = os.path.getsize(path)
    if size < 10000:
        raise GraphError("R2 영상이 비어 있음 (%d바이트)" % size, subcode=2207000)
    return size


def publish_yt(item):
    """R2 → 유튜브 재개 업로드. publish_at 이 15분 이상 앞이면 예약 공개, 아니면 바로 공개. (video_id, 상태) 를 돌려준다"""
    from datetime import timedelta
    when = parse(item["publish_at"])
    ahead = when > now() + timedelta(minutes=15)      # 유튜브는 과거·임박한 publishAt 을 거절한다
    status = ({"privacyStatus": "private", "publishAt": when.strftime("%Y-%m-%dT%H:%M:00+09:00"), "selfDeclaredMadeForKids": False}
              if ahead else {"privacyStatus": "public", "selfDeclaredMadeForKids": False})
    body = {"snippet": {"title": (item.get("yt_title") or item["id"])[:100], "description": (item.get("yt_description") or "")[:5000],
                        "tags": list(item.get("yt_tags") or [])[:30], "categoryId": "24", "defaultLanguage": "ko"},
            "status": status}
    tmp = (Path("/tmp") if Path("/tmp").is_dir() else ROOT) / (item["id"] + ".tmp.mp4")
    try:
        size = yt_download(item["video_url"], str(tmp))
        print("  R2 에서 받음 %.1fMB" % (size / 1e6))
        _, h = yt_call("POST", YT_UPLOAD, body=body, headers={"X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
        loc = h.get("Location")
        if not loc:
            raise GraphError("재개 업로드 주소(Location) 없음")
        with open(tmp, "rb") as f:
            raw = f.read()
        j, _ = yt_call("PUT", loc, raw=raw, headers={"Content-Type": "video/mp4", "Content-Length": str(size)}, timeout=600)
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    vid = j.get("id")
    if not vid:
        raise GraphError("유튜브 응답에 id 없음: %s" % j)
    ch = (j.get("snippet") or {}).get("channelId")
    if ch and ch != YT_CHANNEL_ID:
        # 엉뚱한 채널에 올라감. 토큰이 잘못된 것 → 인증 오류로 취급해 나머지 중단. 올라간 영상은 사람이 지운다
        raise GraphError("올라간 채널이 명운보감이 아님: %s (video %s). PC 에서 token.json 지우고 --auth-only → youtube_token.py" % (ch, vid), code=190)
    return vid, ("예약" if ahead else "공개")


def quota_left():
    """인스타 하루 게시 한도. 조회 실패면 None (게시는 시도)"""
    try:
        d = graph("GET", IG_USER_ID + "/content_publishing_limit", fields="quota_usage,config").get("data", [{}])[0]
        used, total = d.get("quota_usage", 0), d.get("config", {}).get("quota_total", 0)
        print("인스타 게시 한도: %s/%s (24시간)" % (used, total))
        return total - used if total else None
    except GraphError as e:
        print("게시 한도 조회 실패(무시): %s" % e)
        return None


# ── 1) 발행 ────────────────────────────────────────────────────────────
def wait_container(call, cid, fields):
    """FINISHED 면 None, 규격 오류면 GraphError(spec), 5분 넘으면 GraphError(other)"""
    st = {}
    for _ in range(POLL_MAX):
        st = call("GET", cid, fields=fields)
        code = st.get("status_code") or st.get("status")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise GraphError("컨테이너 %s: %s" % (code, st.get("error_message") or st.get("status")), subcode=2207000)
        time.sleep(POLL_SEC)
    raise GraphError("컨테이너 처리 %d분 초과 (status=%s)" % (POLL_SEC * POLL_MAX // 60, code))


def publish_ig(item, save):
    cid = item.get("ig_container_id")
    if cid:
        print("  인스타 이어서: 컨테이너 %s" % cid)
    else:
        r = graph("POST", IG_USER_ID + "/media", media_type="REELS", video_url=item["video_url"],
                  caption=item.get("caption", ""), share_to_feed="false")   # 릴스 탭에만, 피드에 안 띄움 (2026-09-19 사장님 지시)
        cid = r.get("id")
        if not cid:
            raise GraphError("컨테이너 id 없음: %s" % r)
        item["ig_container_id"] = cid
        save()
        print("  인스타 컨테이너 %s 만듦" % cid)
    wait_container(graph, cid, "status_code,status")
    pub = graph("POST", IG_USER_ID + "/media_publish", creation_id=cid)
    mid = pub.get("id")
    if not mid:
        raise GraphError("media_publish 응답에 id 없음: %s" % pub)
    return mid


def th_state(it):
    """스레드 상태. 표시가 없으면: 인스타가 아직 대기인 건은 '대기', 스레드 붙기 전에 이미 인스타 게시된 옛 건은 '없음'(안 올림)"""
    return it.get("threads_status") or ("대기" if it.get("status", "대기") == "대기" else "없음")


_가운데점 = set("·ㆍ•‧∙⋅・")


def 마침표빼기(t, ents=None):
    """팔자오빠 스레드 글은 마침표·가운데점 안 씀 (사장님 2026-09-27). 나가기 직전에 지운다.
    주소(sajuarcade.com)·아이디(@paljaoppa.dm)·숫자(1.5) 속 점은 남긴다. 가운데점·말줄임은 띄어쓰기로.
    ents(가림 위치, 파이썬 글자 단위)를 주면 지운 만큼 위치를 옮겨서 (글, 새 위치) 로 돌려준다 — 안 옮기면 가림이 엉뚱한 데 씌워짐"""
    t = t or ""
    al = lambda c: c.isascii() and c.isalnum()
    out = []   # (글자, 원래 자리)
    for i, c in enumerate(t):
        if c in _가운데점 or c == "…":
            out.append((" ", i))
        elif c == ".":
            run = (i > 0 and t[i - 1] == ".") or (i + 1 < len(t) and t[i + 1] == ".")
            keep = not run and i > 0 and i + 1 < len(t) and al(t[i - 1]) and al(t[i + 1])
            out.append(("." if keep else " ", i))
        else:
            out.append((c, i))
    # 띄어쓰기 두 칸 이상은 한 칸, 줄 앞뒤 띄어쓰기는 뺌
    res = []
    for c, i in out:
        if c in " \t" and (not res or res[-1][0] in " \t\n"):
            continue
        if c == "\n":
            while res and res[-1][0] in " \t":
                res.pop()
        res.append((c, i))
    while res and res[-1][0] in " \t":
        res.pop()
    글 = "".join(c for c, _ in res)
    if ents is None:
        return 글
    새 = []
    for e in ents:
        a, b = e["offset"], e["offset"] + e["length"]
        자리 = [k for k, (_, i) in enumerate(res) if a <= i < b]
        if 자리:
            새.append(dict(e, offset=자리[0], length=자리[-1] - 자리[0] + 1))
    return 글, 새


def threads_text(item):
    """스레드 글: threads_text 가 있으면 그것, 없으면 캡션에서 해시태그 빼고 500자."""
    t = item.get("threads_text")
    if not t:
        t = re.sub(r"\s*#\S+", "", item.get("caption", "")).strip()
        t = re.sub(r"\n{3,}", "\n\n", t)
    return t[:THREADS_TEXT_MAX]


def publish_th(item, save):
    """글만(TEXT) 게시. 영상·이미지 없음 (2026-09-18 스레드 실측: 답글 상위 글 전부 글만). 본문엔 링크 없음."""
    cid = item.get("threads_container_id")
    if cid:
        print("  스레드 이어서: 컨테이너 %s" % cid)
    else:
        extra = {}
        글, 가림 = 마침표빼기(threads_text(item), item.get("threads_entities") or [])   # 마침표·가운데점 지우고 가림 위치도 같이 옮김
        if 가림:                      # 가림(스포일러). PC 에서 AI가 고른 문구 위치. 누르면 보인다
            extra["text_entities"] = json.dumps(가림)
        r = threads("POST", TH_USER_ID + "/threads", media_type="TEXT", text=글, **extra)
        cid = r.get("id")
        if not cid:
            raise GraphError("스레드 컨테이너 id 없음: %s" % r)
        item["threads_container_id"] = cid
        save()
        print("  스레드 컨테이너 %s 만듦" % cid)
    wait_container(threads, cid, "status,error_message")
    pub = threads("POST", TH_USER_ID + "/threads_publish", creation_id=cid)
    mid = pub.get("id")
    if not mid:
        raise GraphError("threads_publish 응답에 id 없음: %s" % pub)
    return mid


def reply_due():
    """마지막 링크 답글 뒤 REPLY_EVERY_DAYS 일이 지났나. 기록 없으면 True."""
    try:
        last = (쇼츠창고.열기().읽기(REPLY_LOG) or {}).get("last")
        if last:
            dt = datetime.strptime(last, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            return datetime.now(KST) - dt >= timedelta(days=REPLY_EVERY_DAYS)
    except Exception:
        pass
    return True


def mark_reply():
    if DRY:
        return
    쇼츠창고.열기().쓰기(REPLY_LOG, {"last": stamp()})


def reply_th(item, mid):
    """게시 뒤 첫 답글에 만세력 문장 + 사이트 링크 (본문 링크 금지라 답글로). 실패해도 본문 게시는 유효 → 기록만."""
    try:
        time.sleep(30)                                     # 본문 게시 직후 바로 쏘면 500 (2026-09-18 고정글에서 겪음)
        r = threads("POST", TH_USER_ID + "/threads", media_type="TEXT", text=마침표빼기(THREADS_REPLY), reply_to_id=mid)
        rcid = r.get("id")
        if not rcid:
            raise GraphError("답글 컨테이너 id 없음: %s" % r)
        wait_container(threads, rcid, "status,error_message")
        pub = threads("POST", TH_USER_ID + "/threads_publish", creation_id=rcid)
        rid = pub.get("id")
        if not rid:
            raise GraphError("답글 threads_publish 응답에 id 없음: %s" % pub)
        item["threads_reply_id"] = rid
        mark_reply()
        print("  스레드 첫 답글(링크) %s" % rid)
    except GraphError as e:
        item["threads_reply_error"] = "%s %s" % (stamp(), e)
        log(LOG_ERR, "%s %s 스레드 답글(링크) 실패 (본문은 게시됨): %s" % (stamp(), item["id"], e))


def fb_state(it):
    """페북 상태. fb_caption 이 있는 건만 대상(PC 가 페북 분기 붙은 뒤 등록한 것). 없으면 '없음'"""
    return it.get("fb_status") or ("대기" if it.get("fb_caption") else "없음")


def fb_upload(video_id, url):
    """rupload 에 file_url 로 올리기(페북이 R2 에서 직접 받아 간다). 성공이면 None"""
    req = urllib.request.Request(RUPLOAD + video_id, b"", method="POST",
                                 headers={"Authorization": "OAuth " + FB_TOKEN, "file_url": url})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body).get("error", {})
        except Exception:
            err = {}
        raise GraphError(err.get("message") or body[:300], code=err.get("code"), subcode=err.get("error_subcode"), http=e.code)
    except Exception as e:
        raise GraphError("전송 실패: %s" % e)
    if not j.get("success"):
        raise GraphError("rupload 응답: %s" % j)


def fb_wait(video_id, phase):
    """status.<phase>.status 가 complete 면 None. error 면 GraphError(spec). 5분 넘으면 GraphError(other)"""
    st = {}
    for _ in range(POLL_MAX):
        st = fb("GET", video_id, fields="status").get("status") or {}
        ph = (st.get(phase) or {}).get("status")
        if ph == "complete":
            return
        if ph == "error" or st.get("video_status") == "error":
            raise GraphError("페북 영상 %s 오류: %s" % (phase, (st.get(phase) or {}).get("errors") or st.get("video_status")), subcode=2207000)
        time.sleep(POLL_SEC)
    raise GraphError("페북 영상 %s %d분 초과 (status=%s)" % (phase, POLL_SEC * POLL_MAX // 60, st.get("video_status")))


def publish_fb(item, save):
    """페이지 릴스: start → rupload(file_url) → 업로드 완료 → finish(PUBLISHED, description). post id 를 돌려준다."""
    vid = item.get("fb_video_id")
    if vid:
        print("  페북 이어서: video %s" % vid)
    else:
        r = fb("POST", PAGE_ID + "/video_reels", upload_phase="start")
        vid = r.get("video_id")
        if not vid:
            raise GraphError("페북 video_id 없음: %s" % r)
        item["fb_video_id"] = vid
        save()
        print("  페북 video %s 만듦" % vid)
    st = (fb("GET", vid, fields="status").get("status") or {})
    if (st.get("uploading_phase") or {}).get("status") != "complete":
        fb_upload(vid, item["video_url"])
        fb_wait(vid, "uploading_phase")
    if (st.get("publishing_phase") or {}).get("status") == "complete":
        return st.get("publishing_phase", {}).get("post_id") or vid    # 이미 게시된 것(지난 회차에 finish 뒤 저장 못 한 경우)
    r = fb("POST", PAGE_ID + "/video_reels", upload_phase="finish", video_id=vid, video_state="PUBLISHED",
           description=item.get("fb_caption", ""))
    if not r.get("success"):
        raise GraphError("페북 finish 응답: %s" % r)
    return r.get("post_id") or vid


# ── 영상 자동 삭제 (2026-09-25 사장님 "하루 뒤에 자동 삭제되지?") ──
# 전에는 PC 가 다음 편을 만들 때만 R2 영상을 지웠다(upload_instagram.cleanup). PC 가 안 돌면 영영 안 지워졌다.
# 이제 액션이 회차마다 본다: 인스타 게시 20시간 뒤(스레드·페북·유튜브가 아직 대기면 48시간까지 둔다) R2 에서 지운다.
# 예약표 줄은 안 지운다 — PC 가 유튜브 주소를 되받아 기록에 옮겨야 해서. "영상삭제" 표시만 남기고 PC 정리가 줄을 뺀다.
CLEANUP_AFTER_H, CLEANUP_MAX_H = 20, 48
R2_VIDEO_PREFIX = "saju-shorts/"          # = PC upload_instagram.R2_PREFIX. 이 밖은 절대 안 지운다


def cleanup_videos(q, t, save):
    창고 = 쇼츠창고.열기()
    gone = 0
    for it in q:
        if it.get("영상삭제") or not it.get("video_url"):
            continue
        key = it.get("key") or (R2_VIDEO_PREFIX + it["id"] + ".mp4")
        if not key.startswith(R2_VIDEO_PREFIX):
            continue
        if it.get("status") == "게시" and it.get("posted_at"):
            base = it["posted_at"]
        elif it.get("status") in ("없음", None) and it.get("fb_status") == "게시" and it.get("fb_posted_at"):
            base = it["fb_posted_at"]
        else:
            continue
        try:
            age_h = (t - parse(base)).total_seconds() / 3600
        except Exception:
            continue
        if age_h < CLEANUP_AFTER_H:
            continue
        if age_h < CLEANUP_MAX_H and "대기" in (it.get("threads_status"), it.get("fb_status"), it.get("youtube_status")):
            continue                                   # 아직 올릴 데가 남았다. 하루 더 둔다
        if DRY:
            print("  [dry-run] 영상 삭제 대상: %s (%s, %.0f시간)" % (it["id"], key, age_h))
            continue
        try:
            창고.s3.delete_object(Bucket=창고.bucket, Key=key)
        except Exception as e:
            log(LOG_ERR, "%s %s 영상 삭제 실패 (다음 회차에 다시): %s" % (stamp(), it["id"], str(e)[:120]))
            continue
        it["영상삭제"] = stamp()
        log(LOG_OK, "%s %s 영상 삭제 (게시 %.0f시간 뒤) %s" % (stamp(), it["id"], age_h, key))
        gone += 1
        save()
    if gone:
        print("영상 %d개 지움" % gone)


def handle_error(it, e, tgt, save):
    """오류 종류별 처리. tgt = 'ig' | 'th'. 인증 오류면 True(이 대상 나머지 건 중단)"""
    if tgt == "ig":
        name, st_key, err_key, att_key, cid_key = "인스타", "status", "last_error", "attempts", "ig_container_id"
    elif tgt == "th":
        name, st_key, err_key, att_key, cid_key = "스레드", "threads_status", "threads_error", "threads_attempts", "threads_container_id"
    elif tgt == "yt":
        name, st_key, err_key, att_key, cid_key = "유튜브", "youtube_status", "youtube_error", "youtube_attempts", "youtube_video_id"
    else:
        name, st_key, err_key, att_key, cid_key = "페북", "fb_status", "fb_error", "fb_attempts", "fb_video_id"
    it[err_key] = "%s %s" % (stamp(), e)
    kind = e.kind
    if kind == "auth":
        log(LOG_ERR, "%s %s %s 인증 오류 (대기 유지): %s" % (stamp(), it["id"], name, e))
        save()
        return True
    if kind == "rate":
        log(LOG_ERR, "%s %s %s 속도 제한 (대기 유지, 다음 회차): %s" % (stamp(), it["id"], name, e))
    elif kind == "spec":
        it[st_key] = "실패"
        it.pop(cid_key, None)
        log(LOG_ERR, "%s %s %s 실패(영상 규격, 재시도 안 함): %s" % (stamp(), it["id"], name, e))
    else:
        it[att_key] = it.get(att_key, 0) + 1
        if it[att_key] >= MAX_ATTEMPTS:
            it[st_key] = "실패"
            log(LOG_ERR, "%s %s %s 실패(%d회 시도): %s" % (stamp(), it["id"], name, it[att_key], e))
        else:
            log(LOG_ERR, "%s %s %s 보류(%d/%d회, 다음 회차 재시도): %s" % (stamp(), it["id"], name, it[att_key], MAX_ATTEMPTS, e))
    save()
    return False


def main():
    # 예약표는 R2 창고. **발행하는 동안 내내 잠근다** — PC 가 그 사이 등록하면 서로 덮어쓴다 (2026-09-25)
    창고 = 쇼츠창고.열기()
    if not DRY and not 창고.잠금_잡기("깃허브-발행", 기다림초=60):
        print("PC 가 예약표를 고치는 중이라 이번 회차는 쉰다 (다음 회차에)")
        return 0
    try:
        return _main(창고)
    finally:
        if not DRY:
            창고.잠금_풀기()


def warn_token_stale(창고, t):
    """토큰 주간 연장(token-refresh)이 9일 넘게 안 됐으면 하루 한 번 알린다 (2026-09-27).
    그 워크플로가 취소·누락되면 실패 메일도 안 와서 60일째 조용히 멈출 수 있었다."""
    try:
        st = 창고.읽기("토큰상태.json") or {}
        갱신 = datetime.strptime(st.get("갱신", ""), "%Y-%m-%d %H:%M").replace(tzinfo=t.tzinfo)
        오늘 = t.strftime("%Y-%m-%d")
        if t - 갱신 < timedelta(days=9) or st.get("오래됨알림") == 오늘 or DRY:
            return
        st["오래됨알림"] = 오늘                      # 토큰갱신.py 가 성공하면 통째로 새로 써서 이 표시도 지워진다
        창고.쓰기("토큰상태.json", st)
        tg_send("⚠ 인스타·스레드·페북 토큰 연장이 %d일째 안 됐어 (마지막 %s).\n"
                "깃허브 insta-shots2 → token-refresh 를 한 번 돌려줘. 60일 되면 올리기가 멈춰"
                % ((t - 갱신).days, st.get("갱신")))
    except Exception as e:
        print("토큰 연장 날짜 확인 못 함: %s" % e)


def _main(창고):
    warn_token_stale(창고, now())
    q = 창고.예약표읽기()
    if not q:
        print("예약표 비어 있음")
        return 0
    t = now()
    warn_pileup(q, t)
    due_ig = [it for it in q if it.get("status", "대기") == "대기" and parse(it["publish_at"]) <= t]

    def save():
        if not DRY:
            창고.예약표쓰기(q)

    if DRY:
        print("[dry-run] 아무것도 바꾸지 않음")
        th_ok = False
        if VAULT_KEY:
            err = check_token()
            if err:
                print("토큰 검사 실패:", err)
            else:
                th_ok = check_threads()
        else:
            print("[dry-run] 금고 열쇠 없음 → 토큰 검사 건너뜀")
        due_th = [it for it in q if th_state(it) == "대기" and parse(it["publish_at"]) <= t] if th_ok else []
        fb_ok = check_fb() if VAULT_KEY and IG_SCOPES else False
        due_fb = [it for it in q if fb_state(it) == "대기" and parse(it["publish_at"]) <= t] if fb_ok else []
        yt_ok = check_youtube() if VAULT_KEY and IG_TOKEN else False
        due_yt = [it for it in q if yt_state(it) == "대기" and parse(it["publish_at"]) <= t] if yt_ok else []
        for it in due_yt:
            print("  유튜브 올릴 것: %s (예약 %s, 시도 %s회) %s" % (it["id"], it["publish_at"], it.get("youtube_attempts", 0), (it.get("yt_title") or "")[:40]))
        for it in due_ig:
            print("  인스타 보낼 것: %s (예약 %s, 시도 %s회, 컨테이너 %s)" % (it["id"], it["publish_at"], it.get("attempts", 0), it.get("ig_container_id", "-")))
        for it in due_th:
            print("  스레드 보낼 것: %s (%d자) %s" % (it["id"], len(threads_text(it)), threads_text(it)[:60].replace("\n", " ")))
        for it in due_fb:
            print("  페북 보낼 것: %s (캡션 %d자, video %s)" % (it["id"], len(it.get("fb_caption", "")), it.get("fb_video_id", "-")))
        if not due_ig and not due_th and not due_fb and not due_yt:
            print("할 일 없음 (%s)" % t.strftime("%Y-%m-%d %H:%M"))
        return 0

    err = check_token()
    if err:
        log(LOG_ERR, "%s 토큰 검사 실패: %s (대기 %d건 그대로 둠)" % (stamp(), err, len(due_ig)))
        return 1
    th_ok = check_threads()
    due_th = [it for it in q if th_state(it) == "대기" and parse(it["publish_at"]) <= t] if th_ok else []
    fb_ok = check_fb()
    due_fb = [it for it in q if fb_state(it) == "대기" and parse(it["publish_at"]) <= t] if fb_ok else []
    yt_ok = check_youtube()
    # 2026-09-22 사장님 지시: 유튜브도 예약 공개 대신 **시각이 지나면 그때 올려 바로 공개** (인스타·스레드·페북과 같게).
    # 깨우기(PC·워커 10분마다)가 있어서 늦어도 10분 + 업로드 1~2분. 이미 예약 공개로 올라간 건은 그대로 둔다.
    due_yt = [it for it in q if yt_state(it) == "대기" and parse(it["publish_at"]) <= t] if yt_ok else []

    due_ig, due_th, due_fb, due_yt = (spread(q, t, due_ig, "ig", save), spread(q, t, due_th, "th", save),
                                      spread(q, t, due_fb, "fb", save), spread(q, t, due_yt, "yt", save))

    retry_th = [it for it in q if it.get("threads_status") == "게시" and not it.get("threads_reply_id") and it.get("threads_reply_error")
                and it.get("threads_reply_attempts", 0) < MAX_ATTEMPTS] if th_ok else []
    cleanup_videos(q, t, save)                  # 게시 20시간 지난 영상은 여기서 지운다 (PC 안 켜도)
    if not due_ig and not due_th and not due_fb and not due_yt and not retry_th:
        print("할 일 없음 (%s)" % t.strftime("%Y-%m-%d %H:%M"))
        return 0

    exit_code = 0
    # 유튜브 (먼저. 예약 공개 시각이 임박하기 전에 올려 둔다)
    for it in due_yt:
        print("유튜브 업로드: %s (예약 %s)" % (it["id"], it["publish_at"]))
        try:
            vid, st = publish_yt(it)
        except GraphError as e:
            if handle_error(it, e, "yt", save):
                break
            continue
        it["youtube_status"] = st
        it["youtube_video_id"] = vid
        it["youtube_url"] = "https://youtube.com/shorts/" + vid
        it["youtube_uploaded_at"] = stamp()
        it.pop("youtube_error", None)
        log(LOG_OK, "%s %s 유튜브 %s (예약 %s) %s %s" % (it["youtube_uploaded_at"], it["id"], st, it["publish_at"], it["youtube_url"], YT_CHANNEL_TITLE))
        save()
    # 인스타
    if due_ig:
        left = quota_left()
        for it in due_ig:
            if left is not None and left <= 0:
                log(LOG_ERR, "%s %s 인스타 보류: 24시간 게시 한도 소진. 다음 회차" % (stamp(), it["id"]))
                continue
            print("인스타 발행: %s (예약 %s)" % (it["id"], it["publish_at"]))
            try:
                mid = publish_ig(it, save)
            except GraphError as e:
                if handle_error(it, e, "ig", save):
                    exit_code = 1
                    break                          # 토큰이 죽었으면 나머지도 안 된다
                continue
            it["status"] = "게시"
            it["posted_at"] = stamp()
            it["ig_media_id"] = mid
            it.pop("last_error", None)
            if left is not None:
                left -= 1
            log(LOG_OK, "%s %s 인스타 게시 (예약 %s) media %s %s" % (it["posted_at"], it["id"], it["publish_at"], mid, it["video_url"]))
            save()
    # 스레드
    for it in due_th:
        print("스레드 발행: %s (예약 %s)" % (it["id"], it["publish_at"]))
        try:
            mid = publish_th(it, save)
        except GraphError as e:
            if handle_error(it, e, "th", save):
                break
            continue
        it["threads_status"] = "게시"
        it["threads_posted_at"] = stamp()
        it["threads_media_id"] = mid
        it.pop("threads_error", None)
        log(LOG_OK, "%s %s 스레드 게시 (예약 %s) post %s @%s" % (it["threads_posted_at"], it["id"], it["publish_at"], mid, TH_USERNAME))
        save()
        if reply_due():
            reply_th(it, mid)
            save()
        else:
            print("  링크 답글 건너뜀 (최근 %d일 안에 달았음)" % REPLY_EVERY_DAYS)
    # 페북 페이지 릴스
    for it in due_fb:
        print("페북 발행: %s (예약 %s)" % (it["id"], it["publish_at"]))
        try:
            pid = publish_fb(it, save)
        except GraphError as e:
            if handle_error(it, e, "fb", save):
                break
            continue
        it["fb_status"] = "게시"
        it["fb_posted_at"] = stamp()
        it["fb_post_id"] = pid
        it.pop("fb_error", None)
        log(LOG_OK, "%s %s 페북 게시 (예약 %s) post %s %s" % (it["fb_posted_at"], it["id"], it["publish_at"], pid, FB_PAGE_NAME))
        save()
    # 본문은 올라갔는데 답글(링크)만 실패한 건 → 다음 회차에 답글만 다시 (3회까지)
    if th_ok:
        for it in q:
            if it.get("threads_status") == "게시" and it.get("threads_media_id") and not it.get("threads_reply_id")                     and it.get("threads_reply_error") and it.get("threads_reply_attempts", 0) < MAX_ATTEMPTS:
                it["threads_reply_attempts"] = it.get("threads_reply_attempts", 0) + 1
                print("스레드 답글 재시도: %s (%d회)" % (it["id"], it["threads_reply_attempts"]))
                reply_th(it, it["threads_media_id"])
                if it.get("threads_reply_id"):
                    it.pop("threads_reply_error", None)
                    log(LOG_OK, "%s %s 스레드 첫 답글(링크) %s" % (stamp(), it["id"], it["threads_reply_id"]))
                save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
