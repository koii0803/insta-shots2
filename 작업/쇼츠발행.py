# -*- coding: utf-8 -*-
"""깃허브 액션이 돌리는 인스타 릴스 발행 스크립트. 사용자가 직접 만질 일 없음.
이 저장소에는 영상이 없다(영상은 Cloudflare R2). 여기서는 예약표(쇼츠예약.json)만 본다.

하는 일 (메타 그래프 API 직접 호출, Make 없음):
  0) 토큰 검사: Secrets 비었거나 토큰이 죽었으면 아무것도 건드리지 않고 오류기록.txt 한 줄 + 종료코드 1 (액션 실패 → 깃허브가 이메일로 알림)
  1) 쇼츠예약.json 에서 publish_at 이 지난 "대기" 건마다
     - ig_container_id 가 이미 있으면 새로 만들지 않고 그 컨테이너 상태부터 본다
     - 없으면 POST /{IG_USER_ID}/media (media_type=REELS, video_url, caption, share_to_feed) → 컨테이너 id 를 예약표에 바로 적는다
     - 컨테이너 status_code 가 FINISHED 될 때까지 10초마다 최대 5분
     - POST /{IG_USER_ID}/media_publish → ig_media_id, posted_at, status "게시"
  2) 오류는 종류별로:
     - 인증(190, 102, 10, 200~299): 대기 유지, 끝에 종료코드 1
     - 속도 제한(4, 17, 32, 613, 하루 한도 소진): 대기 유지, 다음 회차
     - 영상 규격(2207xxx, unsupported/aspect ratio/too short/too long, 컨테이너 ERROR): 즉시 "실패" (다시 해도 안 됨)
     - 그 외(전송 실패, 시간 초과, 9007 등): attempts +1, 3회까지 대기 유지, 넘으면 "실패"
     last_error 에 마지막 이유를 남긴다.
영상 삭제는 PC 쪽 upload_instagram.py --cleanup 이 R2에서 한다(게시 20시간 뒤).
게시 토큰 = 60일 사용자 토큰. 저장소의 금고(토큰.enc)에 암호화돼 있고, 열쇠는 Secrets IG_ACCESS_TOKEN(페이지 토큰). 갱신은 token-refresh 워크플로가 매주.
로컬 시험: python 작업/쇼츠발행.py --dry-run  (토큰 없어도 됨. 아무것도 안 바꿈)
"""
import os
import sys
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "쇼츠예약.json"
LOG_OK = ROOT / "발행기록.txt"
LOG_ERR = ROOT / "오류기록.txt"
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
VAULT_KEY = os.environ.get("IG_ACCESS_TOKEN", "").strip()   # 금고 열쇠(만료 없는 페이지 토큰). 게시에는 안 쓴다
IG_TOKEN = ""                                                 # 게시용 60일 토큰. 금고(토큰.enc)에서 꺼낸다
TOKEN_EXPIRES = 0
IG_USERNAME = "luck.arcade"           # 운빨연구소. 다른 계정이면 게시 전에 멈춘다
GRAPH = "https://graph.facebook.com/v26.0/"
KST = ZoneInfo("Asia/Seoul")
DRY = "--dry-run" in sys.argv
MAX_ATTEMPTS = 3
POLL_SEC, POLL_MAX = 10, 30          # 10초 × 30 = 5분

AUTH_CODES = {190, 102, 10} | set(range(200, 300))
RATE_CODES = {4, 17, 32, 613}
SPEC_WORDS = ("unsupported", "aspect ratio", "too short", "too long", "invalid video", "media download failed", "not supported")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def now():
    return datetime.now(KST).replace(tzinfo=None)


def open_vault():
    """토큰.enc 를 열어 60일 토큰을 IG_TOKEN 에 넣는다. 실패면 이유 문자열."""
    global IG_TOKEN, TOKEN_EXPIRES
    if not VAULT_KEY:
        return "IG_ACCESS_TOKEN(금고 열쇠) 비어 있음"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import 금고
    except ImportError:
        return "pynacl 없음 (워크플로에 pip install pynacl)"
    if not 금고.VAULT.exists():
        # 금고가 아직 없으면 열쇠(페이지 토큰)로 그냥 게시한다. 발행이 끊기는 구간이 없게.
        IG_TOKEN = VAULT_KEY
        print("토큰.enc 없음 → 페이지 토큰으로 게시 (PC 에서 python ig_token.py 하면 60일 토큰으로 바뀜)")
        return None
    try:
        v = 금고.load(VAULT_KEY)
    except Exception as e:
        return "금고를 못 열음(열쇠 태그 %s): %s" % (금고.key_tag(VAULT_KEY), type(e).__name__)
    IG_TOKEN = v.get("user_token", "")
    TOKEN_EXPIRES = v.get("expires_at") or 0
    return None if IG_TOKEN else "금고 안에 토큰 없음"


def stamp():
    return now().strftime("%Y-%m-%d %H:%M")


def parse(t):
    return datetime.strptime(t, "%Y-%m-%d %H:%M")


def log(path, line):
    print(line)
    if not DRY:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


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


def graph(method, path, **params):
    """그래프 API 한 번. 성공이면 dict, 실패면 GraphError"""
    params["access_token"] = IG_TOKEN
    data = urllib.parse.urlencode(params).encode("utf-8")
    url = GRAPH + path
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


# ── 0) 토큰 검사 ──────────────────────────────────────────────────────
def check_token():
    """토큰 값은 절대 출력하지 않는다. 문제면 이유 문자열, 정상이면 None"""
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
    print("토큰:", info, "scopes:", d.get("scopes"))
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


def quota_left():
    """하루 게시 한도. 조회 실패면 None (게시는 시도)"""
    try:
        d = graph("GET", IG_USER_ID + "/content_publishing_limit", fields="quota_usage,config").get("data", [{}])[0]
        used, total = d.get("quota_usage", 0), d.get("config", {}).get("quota_total", 0)
        print("게시 한도: %s/%s (24시간)" % (used, total))
        return total - used if total else None
    except GraphError as e:
        print("게시 한도 조회 실패(무시): %s" % e)
        return None


# ── 1) 발행 ────────────────────────────────────────────────────────────
def wait_container(cid):
    """FINISHED 면 None, 규격 오류면 GraphError(spec), 5분 넘으면 GraphError(other)"""
    st = {}
    for _ in range(POLL_MAX):
        st = graph("GET", cid, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise GraphError("컨테이너 %s: %s" % (code, st.get("status")), subcode=2207000)  # 규격 오류로 분류
        time.sleep(POLL_SEC)
    raise GraphError("컨테이너 처리 %d분 초과 (status=%s)" % (POLL_SEC * POLL_MAX // 60, st.get("status_code")))


def publish(item, save):
    """한 건 게시. 성공이면 media_id. 실패면 GraphError. save() 는 컨테이너 id 를 만들자마자 예약표에 남기는 콜백"""
    cid = item.get("ig_container_id")
    if cid:
        print("  이어서: 컨테이너 %s 상태 확인" % cid)
    else:
        r = graph("POST", IG_USER_ID + "/media", media_type="REELS", video_url=item["video_url"],
                  caption=item.get("caption", ""), share_to_feed="true")
        cid = r.get("id")
        if not cid:
            raise GraphError("컨테이너 id 없음: %s" % r)
        item["ig_container_id"] = cid
        save()
        print("  컨테이너 %s 만듦" % cid)
    wait_container(cid)
    pub = graph("POST", IG_USER_ID + "/media_publish", creation_id=cid)
    mid = pub.get("id")
    if not mid:
        raise GraphError("media_publish 응답에 id 없음: %s" % pub)
    return mid


def main():
    if not QUEUE.exists():
        print("예약표 없음")
        return 0
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    t = now()
    due = [it for it in q if it.get("status", "대기") == "대기" and parse(it["publish_at"]) <= t]

    def save():
        if not DRY:
            QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")

    if DRY:
        print("[dry-run] 아무것도 바꾸지 않음")
        if VAULT_KEY:
            err = check_token()
            if err:
                print("토큰 검사 실패:", err)
        else:
            print("[dry-run] 금고 열쇠 없음 → 토큰 검사 건너뜀")
        for it in due:
            print("  보낼 것: %s (예약 %s, 시도 %s회, 컨테이너 %s) %s" % (
                it["id"], it["publish_at"], it.get("attempts", 0), it.get("ig_container_id", "-"), it["video_url"]))
        if not due:
            print("할 일 없음 (%s)" % t.strftime("%Y-%m-%d %H:%M"))
        return 0

    err = check_token()
    if err:
        log(LOG_ERR, "%s 토큰 검사 실패: %s (대기 %d건 그대로 둠)" % (stamp(), err, len(due)))
        return 1

    if not due:
        print("할 일 없음 (%s)" % t.strftime("%Y-%m-%d %H:%M"))
        return 0

    left = quota_left()
    exit_code = 0
    for it in due:
        if left is not None and left <= 0:
            log(LOG_ERR, "%s %s 보류: 24시간 게시 한도 소진. 다음 회차" % (stamp(), it["id"]))
            continue
        print("발행: %s (예약 %s)" % (it["id"], it["publish_at"]))
        try:
            mid = publish(it, save)
        except GraphError as e:
            kind = e.kind
            it["last_error"] = "%s %s" % (stamp(), e)
            if kind == "auth":
                log(LOG_ERR, "%s %s 인증 오류 (대기 유지, 액션 실패): %s" % (stamp(), it["id"], e))
                exit_code = 1
                save()
                break                              # 토큰이 죽었으면 나머지도 안 된다
            if kind == "rate":
                log(LOG_ERR, "%s %s 속도 제한 (대기 유지, 다음 회차): %s" % (stamp(), it["id"], e))
            elif kind == "spec":
                it["status"] = "실패"
                it.pop("ig_container_id", None)
                log(LOG_ERR, "%s %s 실패(영상 규격, 재시도 안 함): %s" % (stamp(), it["id"], e))
            else:
                it["attempts"] = it.get("attempts", 0) + 1
                if it["attempts"] >= MAX_ATTEMPTS:
                    it["status"] = "실패"
                    log(LOG_ERR, "%s %s 실패(%d회 시도): %s" % (stamp(), it["id"], it["attempts"], e))
                else:
                    log(LOG_ERR, "%s %s 보류(%d/%d회, 다음 회차 재시도): %s" % (stamp(), it["id"], it["attempts"], MAX_ATTEMPTS, e))
            save()
            continue
        it["status"] = "게시"
        it["posted_at"] = stamp()
        it["ig_media_id"] = mid
        it.pop("last_error", None)
        if left is not None:
            left -= 1
        log(LOG_OK, "%s %s 게시 (예약 %s) media %s %s" % (it["posted_at"], it["id"], it["publish_at"], mid, it["video_url"]))
        save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
