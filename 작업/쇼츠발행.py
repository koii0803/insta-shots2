# -*- coding: utf-8 -*-
"""깃허브 액션이 매시간 실행하는 인스타 릴스 발행·정리 스크립트. 사용자가 직접 만질 일 없음.

하는 일:
  1. 쇼츠예약.json 에서 publish_at 이 지난 "대기" 건 → Make 웹훅(MAKE_WEBHOOK_REELS)으로
     {"type":"reel","id","video_url","caption","share_to_feed":true} 전송 → 성공이면 status "게시", posted_at 기록
     실패면 status "실패" + 오류기록.txt 한 줄 (다음 시간에 다시 시도하지 않는다. 사람이 보고 판단)
  2. "게시" 건 중 posted_at + delete_after_hours 가 지난 것 → videos/<id>.mp4 삭제, 예약표에서 제거, 발행기록.txt 한 줄
웹훅 주소는 저장소에 없고 깃허브 Secrets(MAKE_WEBHOOK_REELS)로만 들어온다.
로컬 시험: python 작업/쇼츠발행.py --dry-run  (전송·삭제 없이 무엇을 할지만 찍는다)
"""
import os
import sys
import json
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "쇼츠예약.json"
LOG_OK = ROOT / "발행기록.txt"
LOG_ERR = ROOT / "오류기록.txt"
WEBHOOK = os.environ.get("MAKE_WEBHOOK_REELS", "").strip()
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


def send(item):
    """성공 None, 실패 이유 문자열"""
    body = json.dumps({"type": "reel", "id": item["id"], "video_url": item["video_url"],
                       "caption": item.get("caption", ""), "share_to_feed": True}, ensure_ascii=False).encode("utf-8")
    if DRY:
        return None
    if not WEBHOOK:
        return "MAKE_WEBHOOK_REELS 비어 있음 (저장소 Settings → Secrets 에 등록)"
    req = urllib.request.Request(WEBHOOK, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            if r.status != 200:
                return "Make 응답 %s" % r.status
    except Exception as e:
        return "Make 전송 실패: %s" % e
    return None


def main():
    if not QUEUE.exists():
        print("예약표 없음")
        return
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    t = now()
    changed = False
    keep = []
    for it in q:
        st = it.get("status", "대기")
        if st == "대기" and parse(it["publish_at"]) <= t:
            err = send(it)
            if err:
                it["status"] = "실패"
                log(LOG_ERR, "%s %s 실패: %s" % (t.strftime("%Y-%m-%d %H:%M"), it["id"], err))
            else:
                it["status"] = "게시"
                it["posted_at"] = t.strftime("%Y-%m-%d %H:%M")
                log(LOG_OK, "%s %s 게시 전송 (예약 %s) %s" % (it["posted_at"], it["id"], it["publish_at"], it["video_url"]))
            changed = True
            keep.append(it)
            continue
        if st == "게시" and it.get("posted_at"):
            due = parse(it["posted_at"]) + timedelta(hours=int(it.get("delete_after_hours", 24)))
            if due <= t:
                f = ROOT / it["file"]
                if not DRY and f.exists():
                    f.unlink()
                log(LOG_OK, "%s %s 영상 삭제 (게시 %s 뒤 %s시간)" % (t.strftime("%Y-%m-%d %H:%M"), it["id"], it["posted_at"], it.get("delete_after_hours", 24)))
                changed = True
                continue
        keep.append(it)
    if changed and not DRY:
        QUEUE.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    if not changed:
        print("할 일 없음 (%s)" % t.strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    main()
