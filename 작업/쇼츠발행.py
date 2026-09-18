# -*- coding: utf-8 -*-
"""깃허브 액션이 매시간 실행하는 인스타 릴스 발행 스크립트. 사용자가 직접 만질 일 없음.
이 저장소에는 영상이 없다(영상은 Cloudflare R2). 여기서는 예약표(쇼츠예약.json)만 본다.

하는 일 (2026-09-18부터 Make 없이 메타 그래프 API 직접 호출):
  쇼츠예약.json 에서 publish_at 이 지난 "대기" 건 →
    1) POST /{IG_USER_ID}/media  (media_type=REELS, video_url, caption, share_to_feed)
    2) 컨테이너 status_code 가 FINISHED 될 때까지 기다림 (최대 5분)
    3) POST /{IG_USER_ID}/media_publish
  → 성공이면 status "게시", posted_at, ig_media_id 기록 / 실패면 status "실패" + 오류기록.txt 한 줄 (다시 시도하지 않는다. 사람이 본다)
영상 삭제는 PC 쪽 upload_instagram.py --cleanup 이 R2에서 한다(게시 20시간 뒤).
토큰은 저장소에 없고 깃허브 Secrets(IG_USER_ID, IG_ACCESS_TOKEN)로만 들어온다. 페이지 토큰이라 만료 없음.
로컬 시험: python 작업/쇼츠발행.py --dry-run
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
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
GRAPH = "https://graph.facebook.com/v21.0/"
KST = ZoneInfo("Asia/Seoul")
DRY = "--dry-run" in sys.argv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def now():
    return datetime.now(KST).replace(tzinfo=None)


def parse(t):
    return datetime.strptime(t, "%Y-%m-%d %H:%M")


def log(path, line):
    print(line)
    if not DRY:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def graph(method, path, **params):
    """그래프 API 한 번. 실패면 (None, 이유), 성공이면 (json, None)"""
    params["access_token"] = IG_TOKEN
    data = urllib.parse.urlencode(params).encode("utf-8")
    url = GRAPH + path
    if method == "GET":
        url += "?" + data.decode("utf-8"); data = None
    req = urllib.request.Request(url, data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return None, "HTTP %s %s" % (e.code, body)
    except Exception as e:
        return None, "전송 실패: %s" % e


def send(item):
    """릴스 컨테이너 만들고 → 처리 끝날 때까지 기다리고 → 게시. 성공 (media_id, None), 실패 (None, 이유)"""
    if DRY:
        return "dry", None
    if not IG_USER_ID or not IG_TOKEN:
        return None, "IG_USER_ID / IG_ACCESS_TOKEN 비어 있음 (저장소 Settings → Secrets 에 등록)"
    r, err = graph("POST", IG_USER_ID + "/media", media_type="REELS", video_url=item["video_url"],
                   caption=item.get("caption", ""), share_to_feed="true")
    if err:
        return None, "컨테이너 " + err
    cid = r.get("id")
    if not cid:
        return None, "컨테이너 id 없음: %s" % r
    for _ in range(30):  # 최대 5분
        time.sleep(10)
        st, err = graph("GET", cid, fields="status_code,status")
        if err:
            return None, "상태 확인 " + err
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            return None, "컨테이너 %s: %s" % (code, st.get("status"))
    else:
        return None, "컨테이너 처리 5분 초과 (status=%s)" % st.get("status_code")
    pub, err = graph("POST", IG_USER_ID + "/media_publish", creation_id=cid)
    if err:
        return None, "게시 " + err
    return pub.get("id"), None


def main():
    if not QUEUE.exists():
        print("예약표 없음")
        return
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    t = now()
    changed = False
    for it in q:
        if it.get("status", "대기") == "대기" and parse(it["publish_at"]) <= t:
            media_id, err = send(it)
            if err:
                it["status"] = "실패"
                log(LOG_ERR, "%s %s 실패: %s" % (t.strftime("%Y-%m-%d %H:%M"), it["id"], err))
            else:
                it["status"] = "게시"
                it["posted_at"] = t.strftime("%Y-%m-%d %H:%M")
                it["ig_media_id"] = media_id
                log(LOG_OK, "%s %s 게시 전송 (예약 %s) %s" % (it["posted_at"], it["id"], it["publish_at"], it["video_url"]))
            changed = True
    if changed and not DRY:
        QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    if not changed:
        print("할 일 없음 (%s)" % t.strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    main()
